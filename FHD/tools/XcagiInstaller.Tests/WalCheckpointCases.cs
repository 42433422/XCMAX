using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text.Json;
using System.Threading.Tasks;
using XcagiInstaller.Services;

// 复现 1.0.0.5 强杀后端：已提交事务留在 -wal 里、进程没关连接就退出。
public static class WalCheckpointCases
{
    public static async Task<bool> RunAsync(string root)
    {
        root = Path.Combine(root, "wal-checkpoint-cases"); Directory.CreateDirectory(root);
        var results = new System.Collections.Generic.List<object>();

        var merged = await Abandoned(Path.Combine(root, "merged"));
        var walBefore = Hash(merged + "-wal");
        var evidence = Path.Combine(root, "merged-evidence");
        var didMerge = SqliteWalCheckpoint.CloseAbandonedWal(merged, evidence);
        var raw = Path.Combine(evidence, "database-before-wal-checkpoint");
        var mergedPass = didMerge && !NonEmpty(merged + "-wal") && await Qty(merged) == 6
            && File.Exists(Path.Combine(raw, "checkpoint-record.json")) && Hash(Path.Combine(raw, "xcagi.db-wal")) == walBefore;
        results.Add(new { mode = "abandoned-wal-merged", pass = mergedPass });

        var held = await Abandoned(Path.Combine(root, "held"));
        var heldWal = Hash(held + "-wal"); var heldThrew = false;
        using (new FileStream(held, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
        {
            try { SqliteWalCheckpoint.CloseAbandonedWal(held, Path.Combine(root, "held-evidence")); } catch (IOException) { heldThrew = true; }
        }
        results.Add(new { mode = "database-in-use-refused", pass = heldThrew && Hash(held + "-wal") == heldWal });

        var journal = await Abandoned(Path.Combine(root, "journal"));
        var journalWal = Hash(journal + "-wal"); File.WriteAllText(journal + "-journal", "hot rollback journal");
        var journalMerged = SqliteWalCheckpoint.CloseAbandonedWal(journal, Path.Combine(root, "journal-evidence"));
        results.Add(new { mode = "hot-journal-left-to-guard", pass = !journalMerged && Hash(journal + "-wal") == journalWal });

        var clean = Path.Combine(root, "clean", "xcagi.db"); Directory.CreateDirectory(Path.GetDirectoryName(clean)!);
        await Py("import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.execute('create table inventory(qty integer)');c.commit();c.close()", clean);
        results.Add(new { mode = "clean-database-untouched", pass = !SqliteWalCheckpoint.CloseAbandonedWal(clean, Path.Combine(root, "clean-evidence")) && !Directory.Exists(Path.Combine(root, "clean-evidence")) });

        Console.WriteLine(JsonSerializer.Serialize(new { scope = "SQLite WAL left by a force-killed backend; real winsqlite3 and python sqlite3", results }, new JsonSerializerOptions { WriteIndented = true }));
        return results.All(x => (bool)x.GetType().GetProperty("pass")!.GetValue(x)!);
    }

    static async Task<string> Abandoned(string dir)
    {
        Directory.CreateDirectory(dir); var db = Path.Combine(dir, "xcagi.db");
        await Py("import sqlite3,sys,os;c=sqlite3.connect(sys.argv[1]);c.execute('pragma journal_mode=wal');c.execute('pragma wal_autocheckpoint=0');c.execute('create table inventory(qty integer)');c.executemany('insert into inventory values(?)',[(1,),(2,),(3,)]);c.commit();os._exit(0)", db);
        if (!NonEmpty(db + "-wal")) throw new IOException("fixture did not leave an abandoned WAL");
        return db;
    }
    static bool NonEmpty(string file) => File.Exists(file) && new FileInfo(file).Length != 0;
    static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
    static string Python() => Environment.GetEnvironmentVariable("XCMAX_TEST_PYTHON") ?? "python";
    static async Task<string> Py(string code, string db)
    {
        var p = new Process { StartInfo = new ProcessStartInfo(Python()) { RedirectStandardOutput = true, UseShellExecute = false } };
        p.StartInfo.ArgumentList.Add("-c"); p.StartInfo.ArgumentList.Add(code); p.StartInfo.ArgumentList.Add(db);
        p.Start(); var output = await p.StandardOutput.ReadToEndAsync(); await p.WaitForExitAsync();
        if (p.ExitCode != 0) throw new IOException("python sqlite failed"); return output;
    }
    static async Task<int> Qty(string db) => int.Parse((await Py("import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);print(sum(x[0] for x in c.execute('select qty from inventory')));c.close()", db)).Trim());
}
