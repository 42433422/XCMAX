using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Reflection;

namespace XcagiInstaller.Services;

// Snapshot adapter; the restore/swap/compensation engine remains desktop/rollback-windows.ts.
internal sealed class WindowsUpgradeSnapshot
{
    private readonly string _install, _root, _backup, _marker, _applied, _db, _dbBackup;
    private readonly Dictionary<string, string> _files;
    private string _dbHash = "";
    private string _manifestHash = "";
    private readonly string _fromVersion;
    private readonly string _candidateIdentity = typeof(WindowsUpgradeSnapshot).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? throw new IOException("安装包缺少版本身份。");
    private WindowsUpgradeSnapshot(string install, string root, string? userData)
    {
        _install = install; _root = root; _backup = Path.Combine(root, "app");
        _marker = Path.Combine(userData ?? root, "rollback-marker.json"); _applied = Path.Combine(userData ?? root, "rollback-applied.json");
        _db = userData == null ? "" : Path.Combine(userData, "data", "xcagi.db");
        _dbBackup = _db != "" && File.Exists(_db) ? Path.Combine(root, "database-before.db") : "";
        _fromVersion = "unknown-legacy-installation";
        var identity = Path.Combine(install, "resources", "build-info.json");
        if (File.Exists(identity))
        {
            using var info = JsonDocument.Parse(File.ReadAllText(identity));
            var version = info.RootElement.GetProperty("version").GetString(); var sha = info.RootElement.GetProperty("gitSha").GetString();
            if (string.IsNullOrWhiteSpace(version) || sha == null || !System.Text.RegularExpressions.Regex.IsMatch(sha, "^[0-9a-fA-F]{40}$")) throw new IOException("旧程序版本身份无效，未开始更新。");
            _fromVersion = version + "+" + sha.ToLowerInvariant();
        }
        _files = new();
    }
    private static string Hash(string file) { using var stream = File.OpenRead(file); return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant(); }
    private static bool Inside(string root, string value) => value.Equals(root, StringComparison.OrdinalIgnoreCase) || value.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    private static void NoLinks(string root)
    {
        for (var part = new DirectoryInfo(root); part != null; part = part.Parent)
            if (part.Exists && part.Attributes.HasFlag(FileAttributes.ReparsePoint)) throw new IOException("备份路径含重解析点，未开始安装。");
        foreach (var item in Directory.Exists(root) ? new DirectoryInfo(root).EnumerateFileSystemInfos("*", SearchOption.AllDirectories) : [])
            if (item.Attributes.HasFlag(FileAttributes.ReparsePoint)) throw new IOException("程序目录含链接，未开始安装。");
    }
    private static void EnsureStopped(string install)
    {
        foreach (var process in Process.GetProcesses()) using (process)
        {
            try { if (process.MainModule?.FileName is string file && Inside(install, Path.GetFullPath(file))) throw new IOException("请先从托盘正常退出 XCAGI，再安装更新。"); }
            catch (System.ComponentModel.Win32Exception) { if (process.ProcessName is "XCAGI" or "xcagi-backend") throw new IOException("无法确认旧程序已退出，未开始安装。"); }
            catch (InvalidOperationException) { }
        }
    }
    public static WindowsUpgradeSnapshot? Prepare(string install, string? userData, CancellationToken token)
    {
        install = Path.GetFullPath(install).TrimEnd(Path.DirectorySeparatorChar);
        if (!File.Exists(Path.Combine(install, "XCAGI.exe"))) return null;
        using (var helper = typeof(WindowsUpgradeSnapshot).Assembly.GetManifestResourceStream("XCAGI.WindowsRollback"))
            if (helper == null) throw new IOException("安装包缺少恢复组件，未开始更新。");
        userData = userData == null ? null : Path.GetFullPath(userData).TrimEnd(Path.DirectorySeparatorChar);
        if (userData != null && (Inside(install, userData) || Inside(userData, install))) throw new IOException("程序与业务数据目录不能互相包含。");
        EnsureStopped(install); NoLinks(install);
        if (userData != null && Directory.Exists(userData)) NoLinks(userData);
        var root = Path.Combine(userData ?? Path.GetTempPath(), "rollback", "manual-" + Guid.NewGuid());
        if (Path.Combine(root, "restore.ps1").Length >= 260 || Directory.GetFiles(install, "*", SearchOption.AllDirectories).Any(file => Path.Combine(root, "app", Path.GetRelativePath(install, file)).Length >= 260)) throw new IOException("恢复备份路径超过 Windows 恢复组件限制，未开始更新；请使用较短的用户数据路径。");
        var snapshot = new WindowsUpgradeSnapshot(install, root, userData);
        if (File.Exists(snapshot._marker)) throw new IOException("上次更新尚未确认完成，请先恢复或正常启动原程序。");
        foreach (var suffix in new[] { "-wal", "-journal" })
            if (snapshot._db != "" && File.Exists(snapshot._db + suffix) && new FileInfo(snapshot._db + suffix).Length != 0) throw new IOException("业务数据库尚未正常关闭，未开始更新。");
        Directory.CreateDirectory(snapshot._backup);
        foreach (var file in Directory.GetFiles(install, "*", SearchOption.AllDirectories))
        {
            token.ThrowIfCancellationRequested();
            var relative = Path.GetRelativePath(install, file); var target = Path.Combine(snapshot._backup, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(target)!); File.Copy(file, target);
            var digest = Hash(file); if (Hash(target) != digest) throw new IOException("程序备份校验失败，未开始更新。"); snapshot._files.Add(relative, digest);
        }
        if (snapshot._dbBackup != "")
        {
            using var input = new FileStream(snapshot._db, FileMode.Open, FileAccess.Read, FileShare.None);
            snapshot._dbHash = Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant(); input.Position = 0;
            using var output = File.Create(snapshot._dbBackup); input.CopyTo(output);
        }
        EnsureStopped(install);
        if (snapshot._dbBackup != "" && Hash(snapshot._dbBackup) != snapshot._dbHash) throw new IOException("数据库备份校验失败，未开始更新。");
        using (var marker = new FileStream(snapshot._marker, FileMode.CreateNew, FileAccess.Write, FileShare.None)) JsonSerializer.Serialize(marker, new { mode = "windows-full", fromVersion = snapshot._fromVersion, toVersion = snapshot._candidateIdentity, preparedAt = DateTimeOffset.UtcNow.ToString("O"), appPath = Path.Combine(install, "XCAGI.exe"), backendPath = Path.Combine(install, "resources", "backend", "xcagi-backend.exe"), appBackupRelPath = Path.GetRelativePath(Path.GetDirectoryName(root)!, snapshot._backup), databasePath = snapshot._db, databaseBackupPath = snapshot._dbBackup, databaseOriginallyAbsent = snapshot._db != "" && snapshot._dbBackup == "", expectedAppFiles = snapshot._files, expectedDatabaseSha256 = snapshot._dbHash });
        File.WriteAllText(Path.Combine(root, "snapshot-manifest.json"), JsonSerializer.Serialize(new { appFiles = snapshot._files, databaseSha256 = snapshot._dbHash }), new UTF8Encoding(false));
        snapshot._manifestHash = Hash(Path.Combine(root, "snapshot-manifest.json"));
        return snapshot;
    }
    public async Task RestoreAsync(int exitedInstallerPid)
    {
        EnsureStopped(_install);
        NoLinks(_install);
        if (_db != "") NoLinks(Path.GetDirectoryName(_db)!);
        NoLinks(_backup);
        var manifest = Path.Combine(_root, "snapshot-manifest.json");
        if (!File.Exists(manifest) || Hash(manifest) != _manifestHash) throw new IOException("快照记录缺失或损坏，恢复未执行。");
        if (Directory.GetFiles(_backup, "*", SearchOption.AllDirectories).Length != _files.Count || _files.Any(x => !File.Exists(Path.Combine(_backup, x.Key)) || Hash(Path.Combine(_backup, x.Key)) != x.Value)) throw new IOException("备份缺失或损坏，恢复未执行。");
        using var resource = typeof(WindowsUpgradeSnapshot).Assembly.GetManifestResourceStream("XCAGI.WindowsRollback")!;
        using var reader = new StreamReader(resource); var script = await reader.ReadToEndAsync();
        static string Literal(string value) => "'" + value.Replace("'", "''") + "'";
        var dbHash = _dbHash;
        if (_dbBackup != "" && (!File.Exists(_dbBackup) || Hash(_dbBackup) != dbHash)) throw new IOException("数据库备份缺失或损坏，恢复未执行。");
        var paths = new Dictionary<string, string> { ["installDir"] = _install, ["backupRoot"] = _backup, ["appPath"] = Path.Combine(_install, "XCAGI.exe"), ["markerPath"] = _marker, ["appliedPath"] = _applied, ["logPath"] = Path.Combine(_root, "rollback-helper.log"), ["databasePath"] = _db, ["databaseBackupPath"] = _dbBackup, ["expectedDatabaseSha256"] = dbHash };
        foreach (var pair in paths) script = script.Replace("__" + pair.Key + "__", Literal(pair.Value));
        script = script.Replace("__databaseOriginallyAbsent__", _db != "" && _dbBackup == "" ? "$true" : "$false");
        script = script.Replace("__waitPid__", exitedInstallerPid.ToString()).Replace("__expectedAppFiles__", Convert.ToBase64String(JsonSerializer.SerializeToUtf8Bytes(_files)));
        script = script.Replace("__appliedRecord__", Convert.ToBase64String(JsonSerializer.SerializeToUtf8Bytes(new { appliedAt = DateTimeOffset.UtcNow.ToString("O"), reason = "manual-installer-failed", fromVersion = _candidateIdentity, toVersion = _fromVersion })));
        var scriptPath = Path.Combine(_root, "restore.ps1");
        using (var output = new StreamWriter(new FileStream(scriptPath, FileMode.CreateNew, FileAccess.Write, FileShare.None), new UTF8Encoding(false))) output.Write(script);
        using var loaderResource = typeof(WindowsUpgradeSnapshot).Assembly.GetManifestResourceStream("XCAGI.WindowsRollbackLoader") ?? throw new IOException("恢复加载器缺失，原备份已保留。");
        using var loaderReader = new StreamReader(loaderResource);
        var loader = (await loaderReader.ReadToEndAsync()).Replace("__scriptPath__", Literal(scriptPath)).Replace("__scriptSha256__", Hash(scriptPath));
        File.WriteAllText(Path.Combine(_root, "restore-launch.json"), JsonSerializer.Serialize(new { loaderCharacters = Convert.ToBase64String(Encoding.Unicode.GetBytes(loader)).Length, scriptBytes = new FileInfo(scriptPath).Length, fileCount = _files.Count }), new UTF8Encoding(false));
        var psi = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe")) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in new[] { "-NoProfile", "-NonInteractive", "-EncodedCommand", Convert.ToBase64String(Encoding.Unicode.GetBytes(loader)) }) psi.ArgumentList.Add(arg);
        using var process = Process.Start(psi)!; var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync(); await Task.WhenAll(stdout, stderr);
        if (process.ExitCode != 0 || !File.Exists(_applied)) throw new IOException("恢复未完成，原备份已保留：" + _root + " " + (await stderr).Trim());
        if (Directory.GetFiles(_install, "*", SearchOption.AllDirectories).Length != _files.Count || _files.Any(x => !File.Exists(Path.Combine(_install, x.Key)) || Hash(Path.Combine(_install, x.Key)) != x.Value) || (_dbBackup != "" && Hash(_db) != dbHash) || (_db != "" && _dbBackup == "" && new[] { "", "-wal", "-shm", "-journal" }.Any(suffix => File.Exists(_db + suffix)))) throw new IOException("恢复结果校验失败，原备份已保留：" + _root);
    }
}
