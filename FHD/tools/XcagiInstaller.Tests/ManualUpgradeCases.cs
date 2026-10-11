using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using XcagiInstaller.Services;

public static class ManualUpgradeCases
{
    public static async Task<int?> TryRunChildAsync(string[] args)
    {
        if (args.Length > 0 && args[0] == "--upgrade-holder")
        {
            var py = Python();
            var lockDb = new Process { StartInfo = new ProcessStartInfo(py) { UseShellExecute = false } };
            foreach (var a in new[] { "-c", "import sqlite3,sys,time; c=sqlite3.connect(sys.argv[1],timeout=1); c.execute('BEGIN EXCLUSIVE'); open(sys.argv[2],'w').write('ready');\nwhile not __import__('os').path.exists(sys.argv[3]): time.sleep(.05)\nc.commit()", args[3], args[1], args[2] }) lockDb.StartInfo.ArgumentList.Add(a);
            lockDb.Start(); await lockDb.WaitForExitAsync();
            return 0;
        }
        if (!args.Contains("/S") || Environment.GetEnvironmentVariable("XCMAX_MANUAL_UPGRADE_CHILD") != "1") return null;
        var joined = string.Join(" ", args); var marker = "/D="; var i = joined.LastIndexOf(marker, StringComparison.OrdinalIgnoreCase);
        var dir = joined[(i + marker.Length)..]; var mode = Environment.GetEnvironmentVariable("XCMAX_MANUAL_UPGRADE_MODE") ?? "failure";
        foreach (var name in new[] { "XCAGI.exe", "resources/app.asar", "resources/backend/xcagi-backend.exe", "resources/build-info.json", "new-only.dll" })
        { var p = Path.Combine(dir, name); Directory.CreateDirectory(Path.GetDirectoryName(p)!); File.WriteAllText(p, "candidate-" + name); }
        File.Delete(Path.Combine(dir, "old-only.dll"));
        File.WriteAllText(Path.Combine(dir, "resources/build-info.json"), "{\"version\":\"9.0\",\"gitSha\":\"" + new string('9', 40) + "\"}");
        var childDb = Path.Combine(Environment.GetEnvironmentVariable("XCMAX_MANUAL_UPGRADE_DATA")!, "data", "xcagi.db");
        if (mode == "absent-db")
        {
            await Sql(childDb, "CREATE TABLE inventory(qty INTEGER); INSERT INTO inventory VALUES(1);");
            foreach (var suffix in new[] { "-wal", "-shm", "-journal" }) File.WriteAllText(childDb + suffix, "candidate-sidecar");
        }
        else try { await Sql(childDb, "UPDATE inventory SET qty=1"); } catch { }
        File.WriteAllText(Environment.GetEnvironmentVariable("XCMAX_MANUAL_UPGRADE_READY")!, "ready");
        if (mode == "cancel") await Task.Delay(30000);
        if (mode != "cancel") while (!File.Exists(Environment.GetEnvironmentVariable("XCMAX_MANUAL_UPGRADE_RELEASE")!)) await Task.Delay(30);
        if (mode == "crash") Environment.Exit(unchecked((int)0xC0000005));
        if (mode is "bad-db" or "truncated-db" or "bad-manifest" or "missing-snapshot" or "locked-db") return 7;
        if (mode == "missing-backend") File.Delete(Path.Combine(dir, "resources/backend/xcagi-backend.exe"));
        return mode is "success" or "post-failure" or "missing-backend" ? 0 : 7;
    }

    public static async Task<bool> RunAsync(string root)
    {
        root = Path.Combine(root, "manual-upgrade-cases"); Directory.CreateDirectory(root);
        var results = new List<object>();
        var selectedCase = Environment.GetEnvironmentVariable("XCMAX_MANUAL_UPGRADE_CASE");
        foreach (var mode in new[] { "failure", "crash", "missing-backend", "success", "cancel", "bad-db", "truncated-db", "bad-manifest", "missing-snapshot", "locked-db", "large", "post-failure", "absent-db" }.Where(x => string.IsNullOrEmpty(selectedCase) || x == selectedCase))
        {
            var home = Path.Combine(root, mode + " space ' path"); var app = Path.Combine(home, "installed app"); var data = Path.Combine(home, "user data"); Directory.CreateDirectory(app);
            SeedApp(app, mode == "large" ? 2824 : 5); Directory.CreateDirectory(Path.Combine(data, "data")); var db = Path.Combine(data, "data", "xcagi.db"); var hasOriginalDb = mode != "absent-db"; if (hasOriginalDb) await Sql(db, "CREATE TABLE inventory(qty INTEGER); INSERT INTO inventory VALUES(3);");
            var originalFiles = Hashes(app); var originalDb = hasOriginalDb ? Hash(db) : null; var ready = Path.Combine(home, "ready"); var release = Path.Combine(home, "release");
            Environment.SetEnvironmentVariable("XCMAX_MANUAL_UPGRADE_CHILD", "1"); Environment.SetEnvironmentVariable("XCMAX_MANUAL_UPGRADE_MODE", mode == "large" ? "failure" : mode); Environment.SetEnvironmentVariable("XCMAX_MANUAL_UPGRADE_DATA", data); Environment.SetEnvironmentVariable("XCMAX_MANUAL_UPGRADE_READY", ready); Environment.SetEnvironmentVariable("XCMAX_MANUAL_UPGRADE_RELEASE", release);
            using var cancel = new CancellationTokenSource();
            var progress = new List<InstallProgressUpdate>(); var run = NsisSilentInstaller.RunAsync(Environment.ProcessPath!, app, new Inline(progress.Add), cancel.Token, data);
            await WaitFor(ready, 20000);
            if (mode == "cancel") cancel.CancelAfter(1200);
            var backups = Directory.Exists(Path.Combine(data, "rollback")) ? Directory.GetDirectories(Path.Combine(data, "rollback"), "manual-*") : [];
            var mutated = Hashes(app); var dbMutated = Hash(db);
            if (mode is "bad-db" or "truncated-db") File.WriteAllBytes(Path.Combine(backups.Single(), "database-before.db"), mode == "bad-db" ? [1,2,3] : Array.Empty<byte>());
            if (mode == "bad-manifest") File.WriteAllText(Path.Combine(backups.Single(), "snapshot-manifest.json"), "{");
            if (mode == "missing-snapshot") File.Delete(Path.Combine(backups.Single(), "app", "old-only.dll"));
            if (mode == "locked-db")
            {
                var holder = new Process { StartInfo = new ProcessStartInfo(Environment.ProcessPath!) { UseShellExecute = false } };
                foreach (var a in new[] { "--upgrade-holder", Path.Combine(home, "holder.ready"), Path.Combine(home, "holder.release"), db }) holder.StartInfo.ArgumentList.Add(a);
                holder.Start();
                await WaitFor(Path.Combine(home, "holder.ready"), 10000); File.WriteAllText(release, "go"); var failed = await run; File.WriteAllText(Path.Combine(home, "holder.release"), "go"); await holder.WaitForExitAsync();
                var same = SameFiles(Hashes(app), mutated) && Hash(db) == dbMutated && backups.Any(Directory.Exists); var item = new { mode, pass = !failed.Success && same, appAndDbRemainFailedCandidate = same, backupRetained = backups.Any(Directory.Exists) }; results.Add(item); PrintCase(item); continue;
            }
            File.WriteAllText(release, "go");
            var result = await run; var success = mode == "success";
            var postFailureRecovered = false;
            if (mode == "post-failure" && result.Success)
            {
                var method = typeof(InstallResult).GetMethod("RecoverPostInstallFailureAsync", BindingFlags.Instance | BindingFlags.NonPublic);
                if (method != null)
                {
                    var recovery = (Task<string>)method.Invoke(result, new object[] { "fixture post-install failure" })!;
                    postFailureRecovered = (await recovery).Contains("已恢复升级前的程序与数据", StringComparison.Ordinal);
                }
            }
            var databaseRestored = hasOriginalDb ? Hash(db) == originalDb && await Qty(db) == 3 : !File.Exists(db) && !new[] { "-wal", "-shm", "-journal" }.Any(suffix => File.Exists(db + suffix));
            var restored = SameFiles(Hashes(app), originalFiles) && databaseRestored;
            var rejectHeld = mode is "bad-db" or "truncated-db" or "bad-manifest" or "missing-snapshot";
            var candidateHeld = mode == "absent-db"
                ? SameFiles(Hashes(app), mutated) && Hash(db) == dbMutated && new[] { "-wal", "-shm", "-journal" }.All(suffix => File.Exists(db + suffix))
                : SameFiles(Hashes(app), mutated) && Hash(db) == dbMutated && await Qty(db) == 1;
            var postFailure = mode == "post-failure";
            var pass = (postFailure ? result.Success && postFailureRecovered && restored : result.Success == success && (success ? File.Exists(Path.Combine(app, "new-only.dll")) && !File.Exists(Path.Combine(app, "old-only.dll")) : rejectHeld ? candidateHeld : restored)) && (success || postFailure || !progress.Any(x => x.Percent == 100)) && (!rejectHeld || backups.Any(Directory.Exists));
            if (mode == "large") pass &= File.Exists(Path.Combine(backups.Single(), "restore-launch.json")) && JsonDocument.Parse(File.ReadAllText(Path.Combine(backups.Single(), "restore-launch.json"))).RootElement.GetProperty("loaderCharacters").GetInt32() < 32767;
            var report = new { mode, pass, result.Success, result.Error, restored, postFailureRecovered, honestCompletion = success || postFailure || !progress.Any(x => x.Percent == 100), backupRetained = rejectHeld && backups.Any(Directory.Exists), files = originalFiles.Count }; results.Add(report); PrintCase(report);
        }
        foreach (var n in new[] { "XCMAX_MANUAL_UPGRADE_CHILD", "XCMAX_MANUAL_UPGRADE_MODE", "XCMAX_MANUAL_UPGRADE_DATA", "XCMAX_MANUAL_UPGRADE_READY", "XCMAX_MANUAL_UPGRADE_RELEASE" }) Environment.SetEnvironmentVariable(n, null);
        Console.WriteLine(JsonSerializer.Serialize(new { scope = "Windows source child-process regression; exercises installer wrapper and PowerShell recovery, not NSIS/VM acceptance", results }, new JsonSerializerOptions { WriteIndented = true }));
        return results.All(x => (bool)x.GetType().GetProperty("pass")!.GetValue(x)!);
    }

    static void SeedApp(string dir, int count)
    {
        foreach (var name in new[] { "XCAGI.exe", "resources/app.asar", "resources/backend/xcagi-backend.exe", "resources/build-info.json", "old-only.dll" })
        { var p = Path.Combine(dir, name); Directory.CreateDirectory(Path.GetDirectoryName(p)!); File.WriteAllText(p, name == "resources/build-info.json" ? "{\"version\":\"1.0.0.5\",\"gitSha\":\"" + new string('1', 40) + "\"}" : "old-" + name); }
        for (var i = 0; i < count - 5; i++) File.WriteAllText(Path.Combine(dir, "bulk-" + i.ToString("D4") + ".bin"), "payload" + i);
    }
    static Dictionary<string,string> Hashes(string dir) => Directory.GetFiles(dir, "*", SearchOption.AllDirectories).ToDictionary(p => Path.GetRelativePath(dir,p), Hash);
    static bool SameFiles(Dictionary<string,string> left, Dictionary<string,string> right) => left.Count == right.Count && left.All(x => right.TryGetValue(x.Key, out var hash) && hash == x.Value);
    static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
    static void PrintCase(object item) => Console.WriteLine(JsonSerializer.Serialize(new { scope = "Windows source child-process regression; not NSIS/VM acceptance", result = item }));
    static async Task WaitFor(string path, int ms) { var until = DateTime.UtcNow.AddMilliseconds(ms); while (!File.Exists(path) && DateTime.UtcNow < until) await Task.Delay(25); if (!File.Exists(path)) throw new TimeoutException(path); }
    static string Python() => Environment.GetEnvironmentVariable("XCMAX_TEST_PYTHON") ?? (File.Exists(@"C:\Users\97088\AppData\Local\Programs\Python\Python311\python.exe") ? @"C:\Users\97088\AppData\Local\Programs\Python\Python311\python.exe" : "python");
    static async Task Sql(string db, string sql) { var p = new Process { StartInfo = new ProcessStartInfo(Python()) { UseShellExecute = false } }; p.StartInfo.ArgumentList.Add("-c"); p.StartInfo.ArgumentList.Add("import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.executescript(sys.argv[2]);c.commit();c.close()"); p.StartInfo.ArgumentList.Add(db); p.StartInfo.ArgumentList.Add(sql); p.Start(); await p.WaitForExitAsync(); if (p.ExitCode != 0) throw new IOException("python sqlite failed"); }
    static async Task<int> Qty(string db) { var p = new Process { StartInfo = new ProcessStartInfo(Python()) { RedirectStandardOutput = true, UseShellExecute = false } }; foreach (var a in new[] { "-c", "import sqlite3,sys;print(sum(x[0] for x in sqlite3.connect(sys.argv[1]).execute('select qty from inventory')))" , db }) p.StartInfo.ArgumentList.Add(a); p.Start(); var s = await p.StandardOutput.ReadToEndAsync(); await p.WaitForExitAsync(); return int.Parse(s.Trim()); }
    sealed class Inline(Action<InstallProgressUpdate> callback) : IProgress<InstallProgressUpdate> { public void Report(InstallProgressUpdate value) => callback(value); }
}
