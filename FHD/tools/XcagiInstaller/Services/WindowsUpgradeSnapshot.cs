using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Reflection;

namespace XcagiInstaller.Services;

// Snapshot adapter; the restore/swap/compensation engine remains desktop/rollback-windows.ts.
internal sealed class WindowsUpgradeSnapshot
{
    private readonly string _install, _root, _backup, _marker, _applied, _db, _dbBackup, _userData, _ownedBackup;
    private readonly Dictionary<string, string> _files;
    private readonly Dictionary<string, string> _ownedFiles = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<string> _ownedDirectories = [];
    private string _dbHash = "";
    private string _manifestHash = "";
    private readonly string _fromVersion;
    private readonly string _candidateIdentity = typeof(WindowsUpgradeSnapshot).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? throw new IOException("安装包缺少版本身份。");
    private WindowsUpgradeSnapshot(string install, string root, string? userData)
    {
        _install = install; _root = root; _backup = Path.Combine(root, "app"); _userData = userData ?? ""; _ownedBackup = userData == null ? "" : Path.Combine(root, "owned");
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
    private static IEnumerable<string> EnumerateOwnedFiles(string userData)
    {
        var mods = Path.Combine(userData, "mods");
        if (Directory.Exists(mods)) foreach (var file in Directory.EnumerateFiles(mods, "*", SearchOption.AllDirectories)) yield return file;
        foreach (var file in Directory.EnumerateFiles(userData, "*", SearchOption.TopDirectoryOnly))
            if (System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(file), "^(products|inventory|voice_learning|error_collection)(__[A-Za-z0-9_-]+)?\\.db(?:-(?:wal|shm|journal))?$", System.Text.RegularExpressions.RegexOptions.IgnoreCase)) yield return file;
        var data = Path.Combine(userData, "data");
        if (Directory.Exists(data))
        {
            foreach (var file in Directory.EnumerateFiles(data, "*", SearchOption.TopDirectoryOnly))
                if (System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(file), "^.+\\.db(?:-(?:wal|shm|journal))?$", System.Text.RegularExpressions.RegexOptions.IgnoreCase) && !System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(file), "^xcagi\\.db(?:-(?:wal|shm|journal))?$", System.Text.RegularExpressions.RegexOptions.IgnoreCase)) yield return file;
            var modDbs = Path.Combine(data, "mod_dbs");
            if (Directory.Exists(modDbs)) foreach (var file in Directory.EnumerateFiles(modDbs, "*", SearchOption.AllDirectories))
                if (System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(file), "^.+\\.db(?:-(?:wal|shm|journal))?$", System.Text.RegularExpressions.RegexOptions.IgnoreCase)) yield return file;
        }
    }
    private static IEnumerable<string> EnumerateOwnedDirectories(string userData)
    {
        foreach (var rootName in new[] { "mods", "data" })
        {
            var root = Path.Combine(userData, rootName); if (!Directory.Exists(root)) continue;
            yield return rootName;
            var scan = rootName == "mods" ? root : Path.Combine(root, "mod_dbs");
            if (rootName == "data" && Directory.Exists(scan)) yield return Path.Combine("data", "mod_dbs");
            if (!Directory.Exists(scan)) continue;
            if (rootName == "mods")
            {
                foreach (var directory in Directory.EnumerateDirectories(scan, "*", SearchOption.AllDirectories)) yield return Path.GetRelativePath(userData, directory);
            }
            else foreach (var directory in Directory.EnumerateDirectories(scan, "*", SearchOption.AllDirectories)) yield return Path.GetRelativePath(userData, directory);
        }
    }
    private static void ValidateOwnedState(string userData, out long byteCount, out List<string> files)
    {
        const long maximumSingleFile = 8L * 1024 * 1024 * 1024;
        const long maximumSnapshot = 50L * 1024 * 1024 * 1024;
        byteCount = 0; files = EnumerateOwnedFiles(userData).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        foreach (var file in files)
        {
            var full = Path.GetFullPath(file); if (!Inside(userData, full)) throw new IOException("Mod 或数据库快照路径越出用户数据目录，未开始安装。");
            var info = new FileInfo(full); if (info.Attributes.HasFlag(FileAttributes.ReparsePoint)) throw new IOException("Mod 或数据库包含链接，未开始安装。");
            if (info.Length > maximumSingleFile) throw new IOException("单个 Mod 或数据库文件超过 8 GiB 安全快照边界，未开始安装。");
            byteCount = checked(byteCount + info.Length); if (byteCount > maximumSnapshot) throw new IOException("Mod 与数据库总快照超过 50 GiB 安全边界，未开始安装。");
            if (System.Text.RegularExpressions.Regex.IsMatch(full, "\\.db(?:-(?:wal|shm|journal))?$", System.Text.RegularExpressions.RegexOptions.IgnoreCase))
            {
                using var lockedCheck = new FileStream(full, FileMode.Open, FileAccess.Read, FileShare.None);
            }
        }
        var drive = new DriveInfo(Path.GetPathRoot(userData)!); var reserve = Math.Max(1024L * 1024 * 1024, byteCount / 10);
        if (drive.AvailableFreeSpace < checked(byteCount + reserve)) throw new IOException("可用磁盘空间不足以安全保留已授权 Mod 与数据库快照，未开始安装。");
    }
    public static WindowsUpgradeSnapshot? Prepare(string install, string? userData, CancellationToken token, bool updaterHandoff = false)
    {
        install = Path.GetFullPath(install).TrimEnd(Path.DirectorySeparatorChar);
        if (!File.Exists(Path.Combine(install, "XCAGI.exe"))) return null;
        using (var helper = typeof(WindowsUpgradeSnapshot).Assembly.GetManifestResourceStream("XCAGI.WindowsRollback"))
            if (helper == null) throw new IOException("安装包缺少恢复组件，未开始更新。");
        userData = userData == null ? null : Path.GetFullPath(userData).TrimEnd(Path.DirectorySeparatorChar);
        if (userData != null && (Inside(install, userData) || Inside(userData, install))) throw new IOException("程序与业务数据目录不能互相包含。");
        EnsureStopped(install); NoLinks(install);
        if (userData != null && Directory.Exists(userData)) NoLinks(userData);
        long ownedBytes = 0; List<string> ownedSources = [];
        if (userData != null && Directory.Exists(userData)) ValidateOwnedState(userData, out ownedBytes, out ownedSources);
        var root = Path.Combine(userData ?? Path.GetTempPath(), "rollback", "manual-" + Guid.NewGuid());
        if (Path.Combine(root, "restore.ps1").Length >= 260) throw new IOException("恢复加载器路径过长，未开始更新；请使用较短的用户数据路径。");
        var snapshot = new WindowsUpgradeSnapshot(install, root, userData);
        if (userData != null && Directory.Exists(userData)) snapshot._ownedDirectories.AddRange(EnumerateOwnedDirectories(userData).Distinct(StringComparer.OrdinalIgnoreCase).Order(StringComparer.OrdinalIgnoreCase));
        string? handoffHash = null;
        if (File.Exists(snapshot._marker))
        {
            using var handoff = JsonDocument.Parse(File.ReadAllText(snapshot._marker)); var pending = handoff.RootElement;
            var target = pending.GetProperty("toVersion").GetString()!.Split('+'); var candidate = snapshot._candidateIdentity.Split('+');
            var from = pending.GetProperty("fromVersion").GetString()!.Split('+');
            if (!updaterHandoff || pending.GetProperty("mode").GetString() != "windows-full"
                || target.Length != 2 || candidate.Length != 2 || from.Length != 2
                || target[0] != candidate[0] || target[1].Length < 12 || !candidate[1].StartsWith(target[1], StringComparison.OrdinalIgnoreCase)
                || from[1].Length < 12 || !snapshot._fromVersion.Split('+').Last().StartsWith(from[1], StringComparison.OrdinalIgnoreCase)
                || !DateTimeOffset.TryParse(pending.GetProperty("preparedAt").GetString(), out var prepared) || DateTimeOffset.UtcNow - prepared is var age && (age < TimeSpan.Zero || age > TimeSpan.FromMinutes(15))
                || !Path.GetFullPath(pending.GetProperty("appPath").GetString()!).Equals(Path.Combine(install, "XCAGI.exe"), StringComparison.OrdinalIgnoreCase)
                || !Path.GetFullPath(pending.GetProperty("databasePath").GetString()!).Equals(snapshot._db, StringComparison.OrdinalIgnoreCase))
                throw new IOException("上次更新尚未确认完成，请先恢复或正常启动原程序。");
            handoffHash = Hash(snapshot._marker);
        }
        foreach (var retained in new[] { install + ".xcagi-rollback-staging", install + ".xcagi-failed", snapshot._db + ".xcagi-rollback-staging", snapshot._db + ".xcagi-failed" })
            if (retained.Length > install.Length && (Directory.Exists(retained) || File.Exists(retained))) throw new IOException("发现上次恢复暂存或失败现场，未开始更新；请先保留并恢复该现场：" + retained);
        foreach (var owned in ownedSources)
            foreach (var suffix in new[] { ".xcagi-rollback-staging", ".xcagi-failed" })
                if (File.Exists(owned + suffix) || Directory.Exists(owned + suffix)) throw new IOException("发现已授权 Mod/数据库的恢复暂存或失败现场，未开始更新：" + owned + suffix);
        // 旧版本强杀后端留下的 WAL：确认无人占用后先另存原样副本再合并，下面的保护照旧生效。
        if (snapshot._db != "") SqliteWalCheckpoint.CloseAbandonedWal(snapshot._db, root);
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
        if (snapshot._userData != "")
        {
            Directory.CreateDirectory(snapshot._ownedBackup);
            foreach (var relative in snapshot._ownedDirectories) Directory.CreateDirectory(Path.Combine(snapshot._ownedBackup, relative));
            foreach (var source in ownedSources)
            {
                token.ThrowIfCancellationRequested();
                var relative = Path.GetRelativePath(snapshot._userData, source); var target = Path.Combine(snapshot._ownedBackup, relative);
                if (!Inside(snapshot._ownedBackup, Path.GetFullPath(target))) throw new IOException("Mod 快照路径越界，未开始安装。");
                Directory.CreateDirectory(Path.GetDirectoryName(target)!); File.Copy(source, target);
                var digest = Hash(source); if (Hash(target) != digest) throw new IOException("Mod 或数据库快照校验失败，未开始安装。"); snapshot._ownedFiles.Add(relative, digest);
            }
        }
        EnsureStopped(install);
        if (snapshot._dbBackup != "" && Hash(snapshot._dbBackup) != snapshot._dbHash) throw new IOException("数据库备份校验失败，未开始更新。");
        var markerPath = handoffHash == null ? snapshot._marker : Path.Combine(root, "handoff-marker.json");
        using (var marker = new FileStream(markerPath, FileMode.CreateNew, FileAccess.Write, FileShare.None)) JsonSerializer.Serialize(marker, new { mode = "windows-full", fromVersion = snapshot._fromVersion, toVersion = snapshot._candidateIdentity, preparedAt = DateTimeOffset.UtcNow.ToString("O"), appPath = Path.Combine(install, "XCAGI.exe"), backendPath = Path.Combine(install, "resources", "backend", "xcagi-backend.exe"), appBackupRelPath = Path.GetRelativePath(Path.GetDirectoryName(root)!, snapshot._backup), databasePath = snapshot._db, databaseBackupPath = snapshot._dbBackup, databaseOriginallyAbsent = snapshot._db != "" && snapshot._dbBackup == "", expectedAppFiles = snapshot._files, expectedDatabaseSha256 = snapshot._dbHash, ownedUserDataRoot = snapshot._userData, ownedBackupRoot = snapshot._ownedBackup, expectedOwnedFiles = snapshot._ownedFiles, expectedOwnedDirectories = snapshot._ownedDirectories });
        File.WriteAllText(Path.Combine(root, "snapshot-manifest.json"), JsonSerializer.Serialize(new { appFiles = snapshot._files, databaseSha256 = snapshot._dbHash, ownedFiles = snapshot._ownedFiles, ownedDirectories = snapshot._ownedDirectories }), new UTF8Encoding(false));
        snapshot._manifestHash = Hash(Path.Combine(root, "snapshot-manifest.json"));
        if (handoffHash != null)
        {
            if (Hash(snapshot._marker) != handoffHash) throw new IOException("更新交接记录已改变，未开始安装。");
            File.Replace(markerPath, snapshot._marker, Path.Combine(root, "desktop-marker.previous.json"));
        }
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
        if (_ownedBackup != "" && (_ownedFiles.Any(x => !File.Exists(Path.Combine(_ownedBackup, x.Key)) || Hash(Path.Combine(_ownedBackup, x.Key)) != x.Value) || Directory.GetFiles(_ownedBackup, "*", SearchOption.AllDirectories).Length != _ownedFiles.Count)) throw new IOException("Mod 或数据库备份缺失或损坏，恢复未执行。");
        using var resource = typeof(WindowsUpgradeSnapshot).Assembly.GetManifestResourceStream("XCAGI.WindowsRollback")!;
        using var reader = new StreamReader(resource); var script = await reader.ReadToEndAsync();
        static string Literal(string value) => "'" + value.Replace("'", "''") + "'";
        var dbHash = _dbHash;
        if (_dbBackup != "" && (!File.Exists(_dbBackup) || Hash(_dbBackup) != dbHash)) throw new IOException("数据库备份缺失或损坏，恢复未执行。");
        var paths = new Dictionary<string, string> { ["installDir"] = _install, ["backupRoot"] = _backup, ["appPath"] = Path.Combine(_install, "XCAGI.exe"), ["markerPath"] = _marker, ["appliedPath"] = _applied, ["logPath"] = Path.Combine(_root, "rollback-helper.log"), ["databasePath"] = _db, ["databaseBackupPath"] = _dbBackup, ["expectedDatabaseSha256"] = dbHash, ["ownedUserDataRoot"] = _userData, ["ownedBackupRoot"] = _ownedBackup };
        foreach (var pair in paths) script = script.Replace("__" + pair.Key + "__", Literal(pair.Value));
        script = script.Replace("__databaseOriginallyAbsent__", _db != "" && _dbBackup == "" ? "$true" : "$false");
        script = script.Replace("__waitPid__", exitedInstallerPid.ToString()).Replace("__expectedAppFiles__", Convert.ToBase64String(JsonSerializer.SerializeToUtf8Bytes(_files))).Replace("__expectedOwnedFiles__", Convert.ToBase64String(JsonSerializer.SerializeToUtf8Bytes(_ownedFiles))).Replace("__expectedOwnedDirectories__", Convert.ToBase64String(JsonSerializer.SerializeToUtf8Bytes(_ownedDirectories)));
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
        if (_userData != "")
        {
            var restored = EnumerateOwnedFiles(_userData).ToDictionary(file => Path.GetRelativePath(_userData, file), file => Hash(file), StringComparer.OrdinalIgnoreCase);
            if (restored.Count != _ownedFiles.Count || _ownedFiles.Any(x => !restored.TryGetValue(x.Key, out var digest) || digest != x.Value)) throw new IOException("Mod 或数据库恢复结果校验失败，原备份已保留：" + _root);
        }
    }
}
