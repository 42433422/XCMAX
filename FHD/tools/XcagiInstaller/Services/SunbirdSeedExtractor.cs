using System.IO.Compression;
using System.Reflection;

namespace XcagiInstaller.Services;

/// <summary>太阳鸟定制安装包内嵌的业务数据（模板、花名册、Mod 侧库等）。</summary>
public static class SunbirdSeedExtractor
{
    public const string SeedResourceName = "XCAGI.SunbirdSeedPayload";

    public static bool HasEmbeddedSeed() =>
        typeof(SunbirdSeedExtractor).Assembly
            .GetManifestResourceNames()
            .Any(n => n.Equals(SeedResourceName, StringComparison.Ordinal));

    public static async Task<bool> DeployToUserDataAsync(
        string? userDataRoot = null,
        IProgress<string>? progress = null,
        CancellationToken cancellationToken = default)
    {
        if (!HasEmbeddedSeed())
            return false;

        await using var stream = typeof(SunbirdSeedExtractor).Assembly
            .GetManifestResourceStream(SeedResourceName);
        if (stream == null)
            return false;

        var root = userDataRoot ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "XCAGI");
        Directory.CreateDirectory(root);

        var tempZip = Path.Combine(
            Path.GetTempPath(),
            $"xcagi-sunbird-seed-{Guid.NewGuid():N}.zip");
        try
        {
            progress?.Report("正在写入太阳鸟业务数据…");
            await using (var outStream = new FileStream(
                             tempZip,
                             FileMode.Create,
                             FileAccess.Write,
                             FileShare.None,
                             bufferSize: 1024 * 1024,
                             useAsync: true))
            {
                await stream.CopyToAsync(outStream, cancellationToken).ConfigureAwait(false);
            }

            using var archive = ZipFile.OpenRead(tempZip);
            foreach (var entry in archive.Entries)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (string.IsNullOrEmpty(entry.Name) && entry.FullName.EndsWith('/'))
                {
                    Directory.CreateDirectory(Path.Combine(root, entry.FullName.TrimEnd('/')));
                    continue;
                }

                if (string.IsNullOrEmpty(entry.Name))
                    continue;

                var destPath = Path.Combine(root, entry.FullName.Replace('/', Path.DirectorySeparatorChar));
                var destDir = Path.GetDirectoryName(destPath);
                if (!string.IsNullOrEmpty(destDir))
                    Directory.CreateDirectory(destDir);

                entry.ExtractToFile(destPath, overwrite: true);
            }

            var rosterApplied = Path.Combine(root, "config", "sunbird-roster.applied");
            if (File.Exists(rosterApplied))
                File.Delete(rosterApplied);

            progress?.Report("太阳鸟业务数据已就绪");
            return true;
        }
        finally
        {
            try
            {
                if (File.Exists(tempZip))
                    File.Delete(tempZip);
            }
            catch
            {
                // ignore
            }
        }
    }
}
