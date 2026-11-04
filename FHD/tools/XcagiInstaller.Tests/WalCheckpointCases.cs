using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Threading.Tasks;
using XcagiInstaller.Services;

// 复现 1.0.0.5 强杀后端：已提交事务留在 -wal 里，进程没关连接就退出。
public static class WalCheckpointCases
{
    public static async Task<bool> RunAsync(string root)
    {
        root = Path.Combine(root, "wal-checkpoint-cases");
        var merged = await Abandoned(Path.Combine(root, "merged")); var mergedWal = Hash(merged + "-wal"); var raw = Path.Combine(root, "merged-evidence", "database-before-wal-checkpoint");
        var mergedPass = SqliteWalCheckpoint.CloseAbandonedWal(merged, Path.Combine(root, "merged-evidence")) && !NonEmpty(merged + "-wal") && (await Py("import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);print(sum(x[0] for x in c.execute('select qty from inventory')));c.close()", merged)).Trim() == "6"
            && File.Exists(Path.Combine(raw, "checkpoint-record.json")) && Hash(Path.Combine(raw, "xcagi.db-wal")) == mergedWal;
        var held = await Abandoned(Path.Combine(root, "held")); var heldWal = Hash(held + "-wal"); var heldRefused = false;
        using (new FileStream(held, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)) try { SqliteWalCheckpoint.CloseAbandonedWal(held, Path.Combine(root, "held-evidence")); } catch (IOException) { heldRefused = true; }
        var journal = await Abandoned(Path.Combine(root, "journal")); var journalWal = Hash(journal + "-wal"); File.WriteAllText(journal + "-journal", "hot rollback journal");
        var journalLeft = !SqliteWalCheckpoint.CloseAbandonedWal(journal, Path.Combine(root, "journal-evidence")) && Hash(journal + "-wal") == journalWal;
        Console.WriteLine($"{{\"scope\":\"SQLite WAL left by a force-killed backend\",\"merged\":{mergedPass.ToString().ToLower()},\"inUseRefused\":{(heldRefused && Hash(held + "-wal") == heldWal).ToString().ToLower()},\"hotJournalLeftToGuard\":{journalLeft.ToString().ToLower()}}}");
        return mergedPass && heldRefused && Hash(held + "-wal") == heldWal && journalLeft;
    }
    static async Task<string> Abandoned(string dir)
    {
        Directory.CreateDirectory(dir); var db = Path.Combine(dir, "xcagi.db");
        await Py("import sqlite3,sys,os;c=sqlite3.connect(sys.argv[1]);c.execute('pragma journal_mode=wal');c.execute('pragma wal_autocheckpoint=0');c.execute('create table inventory(qty integer)');c.executemany('insert into inventory values(?)',[(1,),(2,),(3,)]);c.commit();os._exit(0)", db);
        return NonEmpty(db + "-wal") ? db : throw new IOException("fixture did not leave an abandoned WAL");
    }
    static bool NonEmpty(string file) => File.Exists(file) && new FileInfo(file).Length != 0;
    static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
    static async Task<string> Py(string code, string db)
    {
        var p = new Process { StartInfo = new ProcessStartInfo(Environment.GetEnvironmentVariable("XCMAX_TEST_PYTHON") ?? "python") { RedirectStandardOutput = true, UseShellExecute = false } };
        foreach (var a in new[] { "-c", code, db }) p.StartInfo.ArgumentList.Add(a);
        p.Start(); var output = await p.StandardOutput.ReadToEndAsync(); await p.WaitForExitAsync();
        return p.ExitCode == 0 ? output : throw new IOException("python sqlite failed");
    }
}
