using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace XcagiInstaller.Services;

// 1.0.0.5 及更早的桌面端停后端是 taskkill /T /F，SQLite 来不及 checkpoint，已提交事务留在 xcagi.db-wal，
// -wal 非空保护因此拒绝所有来自 1.0.0.5 的更新。仅当旧程序已退出、库文件可独占打开、没有 -journal 时，
// 先校验另存原样 db/-wal/-shm，再用系统 SQLite 合并截断 WAL 并 quick_check；保护本身不改，任何一步失败都抛错。
public static class SqliteWalCheckpoint
{
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern int sqlite3_open_v2(byte[] filename, out IntPtr db, int flags, IntPtr vfs);
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern int sqlite3_close_v2(IntPtr db);
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern int sqlite3_prepare_v2(IntPtr db, byte[] sql, int bytes, out IntPtr statement, IntPtr tail);
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern int sqlite3_step(IntPtr statement);
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern int sqlite3_finalize(IntPtr statement);
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern IntPtr sqlite3_column_text(IntPtr statement, int column);
    private static bool NonEmpty(string file) => File.Exists(file) && new FileInfo(file).Length != 0;
    private static string Hash(string file) { using var stream = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.None); return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant(); }
    private static byte[] Utf8(string value) => Encoding.UTF8.GetBytes(value + "\0");

    /// <summary>Returns true when an abandoned WAL was merged; false when there was nothing this helper may merge.</summary>
    public static bool CloseAbandonedWal(string database, string evidenceRoot)
    {
        string wal = database + "-wal", journal = database + "-journal";
        if (!File.Exists(database) || !NonEmpty(wal) || NonEmpty(journal)) return false;
        var sidecars = new[] { database, wal, database + "-shm" }.Where(File.Exists).ToArray();
        foreach (var file in sidecars) using (new FileStream(file, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
        var raw = Path.Combine(evidenceRoot, "database-before-wal-checkpoint"); Directory.CreateDirectory(raw);
        if (new DriveInfo(Path.GetPathRoot(Path.GetFullPath(raw))!).AvailableFreeSpace < checked(sidecars.Sum(f => new FileInfo(f).Length) * 2 + (512L << 20))) throw new IOException("可用磁盘空间不足以先保留业务数据库原样副本，未开始更新。");
        var before = new Dictionary<string, string>();
        foreach (var file in sidecars)
        {
            var target = Path.Combine(raw, Path.GetFileName(file)); File.Copy(file, target);
            var digest = Hash(file); if (Hash(target) != digest) throw new IOException("业务数据库原样副本校验失败，未开始更新。"); before[Path.GetFileName(file)] = digest;
        }
        string[] checkpoint; string quickCheck;
        if (sqlite3_open_v2(Utf8(database), out var db, 0x2 | 0x10000, IntPtr.Zero) != 0) { sqlite3_close_v2(db); throw new IOException("无法打开业务数据库合并未关闭的日志，未开始更新。"); }
        try
        {
            checkpoint = Query(db, "PRAGMA wal_checkpoint(TRUNCATE);", 3);
            if (checkpoint[0] != "0" || checkpoint[1] != checkpoint[2]) throw new IOException("业务数据库日志未能完整合并，未开始更新。");
            if ((quickCheck = Query(db, "PRAGMA quick_check;", 1)[0]) != "ok") throw new IOException("业务数据库完整性检查未通过，未开始更新。");
        }
        finally { if (sqlite3_close_v2(db) != 0) throw new IOException("业务数据库未能正常关闭，未开始更新。"); }
        if (NonEmpty(wal) || NonEmpty(journal)) throw new IOException("业务数据库尚未正常关闭，未开始更新。");
        File.WriteAllText(Path.Combine(raw, "checkpoint-record.json"), JsonSerializer.Serialize(new { reason = "previous desktop force-killed the backend before SQLite closed", mergedAt = DateTimeOffset.UtcNow.ToString("O"), walFrames = checkpoint[1], checkpointedFrames = checkpoint[2], quickCheck, sha256Before = before, databaseSha256After = Hash(database) }), new UTF8Encoding(false));
        return true;
    }

    private static string[] Query(IntPtr db, string sql, int columns)
    {
        if (sqlite3_prepare_v2(db, Utf8(sql), -1, out var statement, IntPtr.Zero) != 0) throw new IOException("业务数据库命令准备失败，未开始更新。");
        try
        {
            if (sqlite3_step(statement) != 100) throw new IOException("业务数据库命令没有返回结果，未开始更新。");
            return Enumerable.Range(0, columns).Select(i => Marshal.PtrToStringUTF8(sqlite3_column_text(statement, i)) ?? "").ToArray();
        }
        finally { sqlite3_finalize(statement); }
    }
}
