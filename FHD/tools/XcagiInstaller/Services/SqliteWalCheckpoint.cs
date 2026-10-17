using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace XcagiInstaller.Services;

// 1.0.0.5 及更早的桌面端停后端时直接 taskkill /T /F，SQLite 没有机会在关闭连接时 checkpoint，
// 已提交的事务留在 xcagi.db-wal 里，候选安装器的 -wal 非空保护因此拒绝所有来自 1.0.0.5 的更新。
// 这里只在旧程序全部退出、库文件无人占用、没有回滚日志（-journal）时，先把原始 db/-wal/-shm
// 校验后另存，再用系统自带 SQLite 把 WAL 合并回主库并截断。-wal 非空保护本身不改，
// 合并没做完或任何一步失败都会抛错，调用方照旧拒绝更新。
public static class SqliteWalCheckpoint
{
    private const int SqliteOk = 0, SqliteRow = 100, SqliteDone = 101, OpenReadWrite = 0x2, OpenFullMutex = 0x10000;
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern int sqlite3_open_v2(byte[] filename, out IntPtr db, int flags, IntPtr vfs);
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern int sqlite3_close_v2(IntPtr db);
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern int sqlite3_prepare_v2(IntPtr db, byte[] sql, int bytes, out IntPtr statement, IntPtr tail);
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern int sqlite3_step(IntPtr statement);
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern int sqlite3_finalize(IntPtr statement);
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern int sqlite3_column_int(IntPtr statement, int column);
    [DllImport("winsqlite3", CallingConvention = CallingConvention.StdCall)] private static extern IntPtr sqlite3_column_text(IntPtr statement, int column);

    private static bool NonEmpty(string file) => File.Exists(file) && new FileInfo(file).Length != 0;
    private static string Hash(string file) { using var stream = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.None); return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant(); }
    private static byte[] Utf8(string value) => Encoding.UTF8.GetBytes(value + "\0");

    /// <summary>Returns true when an abandoned WAL was merged; false when there was nothing to merge.</summary>
    public static bool CloseAbandonedWal(string database, string evidenceRoot)
    {
        var wal = database + "-wal"; var shm = database + "-shm"; var journal = database + "-journal";
        if (!File.Exists(database) || !NonEmpty(wal)) return false;
        // 回滚日志非空说明有未完成事务，交给原有保护拒绝，不在安装器里做恢复。
        if (NonEmpty(journal)) return false;
        var sidecars = new[] { database, wal, shm }.Where(File.Exists).ToArray();
        foreach (var file in sidecars)
            using (new FileStream(file, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
        long bytes = sidecars.Sum(file => new FileInfo(file).Length);
        Directory.CreateDirectory(evidenceRoot);
        var drive = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(evidenceRoot))!);
        if (drive.AvailableFreeSpace < checked(bytes * 2 + 512L * 1024 * 1024)) throw new IOException("可用磁盘空间不足以先保留业务数据库原样副本，未开始更新。");
        var raw = Path.Combine(evidenceRoot, "database-before-wal-checkpoint");
        Directory.CreateDirectory(raw);
        var before = new Dictionary<string, string>();
        foreach (var file in sidecars)
        {
            var target = Path.Combine(raw, Path.GetFileName(file));
            File.Copy(file, target, overwrite: false);
            var digest = Hash(file); if (Hash(target) != digest) throw new IOException("业务数据库原样副本校验失败，未开始更新。");
            before[Path.GetFileName(file)] = digest;
        }
        var walBytes = new FileInfo(wal).Length;
        int busy, logFrames, checkpointed; string quickCheck;
        if (sqlite3_open_v2(Utf8(database), out var db, OpenReadWrite | OpenFullMutex, IntPtr.Zero) != SqliteOk)
        {
            if (db != IntPtr.Zero) sqlite3_close_v2(db);
            throw new IOException("无法打开业务数据库合并未关闭的日志，未开始更新。");
        }
        try
        {
            var row = Query(db, "PRAGMA wal_checkpoint(TRUNCATE);", 3);
            busy = int.Parse(row[0]); logFrames = int.Parse(row[1]); checkpointed = int.Parse(row[2]);
            if (busy != 0 || logFrames != checkpointed) throw new IOException("业务数据库日志未能完整合并，未开始更新。");
            quickCheck = Query(db, "PRAGMA quick_check;", 1)[0];
            if (quickCheck != "ok") throw new IOException("业务数据库完整性检查未通过，未开始更新。");
        }
        finally
        {
            if (sqlite3_close_v2(db) != SqliteOk) throw new IOException("业务数据库未能正常关闭，未开始更新。");
        }
        if (NonEmpty(wal) || NonEmpty(journal)) throw new IOException("业务数据库尚未正常关闭，未开始更新。");
        File.WriteAllText(Path.Combine(raw, "checkpoint-record.json"), JsonSerializer.Serialize(new
        {
            reason = "previous desktop stopped the backend without closing SQLite (taskkill /F)",
            mergedAt = DateTimeOffset.UtcNow.ToString("O"),
            walBytesBefore = walBytes, walFrames = logFrames, checkpointedFrames = checkpointed, quickCheck,
            sha256Before = before, databaseSha256After = Hash(database),
        }), new UTF8Encoding(false));
        return true;
    }

    private static string[] Query(IntPtr db, string sql, int columns)
    {
        if (sqlite3_prepare_v2(db, Utf8(sql), -1, out var statement, IntPtr.Zero) != SqliteOk) throw new IOException("业务数据库命令准备失败，未开始更新。");
        try
        {
            if (sqlite3_step(statement) != SqliteRow) throw new IOException("业务数据库命令没有返回结果，未开始更新。");
            var values = new string[columns];
            for (var i = 0; i < columns; i++) values[i] = Marshal.PtrToStringUTF8(sqlite3_column_text(statement, i)) ?? "";
            var next = sqlite3_step(statement);
            if (next != SqliteDone && next != SqliteRow) throw new IOException("业务数据库命令执行失败，未开始更新。");
            return values;
        }
        finally { sqlite3_finalize(statement); }
    }
}
