using System.Security.Cryptography;
using System.Windows;
using XcagiInstaller.Services;

namespace XcagiInstaller;

public partial class App : System.Windows.Application
{
    protected override async void OnStartup(StartupEventArgs e)
    {
        var options = SilentInstallOptions.Parse(e.Args);
        if (!options.Enabled)
        {
            base.OnStartup(e);
            return;
        }

        ShutdownMode = ShutdownMode.OnExplicitShutdown;
        try
        {
            NsisSilentInstaller.Trace("silent install start");
            var setupExe = await PayloadLocator.ResolveSetupExeAsync(
                cancellationToken: CancellationToken.None).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(setupExe))
                throw new InvalidOperationException("Unable to resolve embedded setup payload.");
            NsisSilentInstaller.Trace($"payload={setupExe};{DescribeFile(setupExe)}");

            var result = await NsisSilentInstaller.RunAsync(
                setupExe,
                options.InstallDirectory ?? NsisSilentInstaller.DefaultInstallDirectory(),
                cancellationToken: CancellationToken.None).ConfigureAwait(false);
            if (!result.Success)
                throw new InvalidOperationException(result.Error ?? "Silent install failed.");
            NsisSilentInstaller.Trace($"installed={result.InstallDir};app={result.AppExePath}");

            if (options.DeploySunbirdSeed && SunbirdSeedExtractor.HasEmbeddedSeed())
            {
                await SunbirdSeedExtractor.DeployToUserDataAsync(
                    cancellationToken: CancellationToken.None).ConfigureAwait(false);
                NsisSilentInstaller.Trace("sunbird seed deployed");
            }

            ShutdownOnUiThread(0);
        }
        catch (Exception ex)
        {
            NsisSilentInstaller.Trace("failed: " + ex);
            ShutdownOnUiThread(1);
        }
    }

    private void ShutdownOnUiThread(int exitCode)
    {
        if (Dispatcher.CheckAccess())
        {
            Shutdown(exitCode);
            return;
        }

        Dispatcher.Invoke(() => Shutdown(exitCode));
    }

    private static string DescribeFile(string path)
    {
        try
        {
            using var sha = SHA256.Create();
            using var stream = File.OpenRead(path);
            var hash = Convert.ToHexString(sha.ComputeHash(stream)).ToLowerInvariant();
            return $"size={new FileInfo(path).Length};sha256={hash}";
        }
        catch (Exception ex)
        {
            return $"describe_error={ex.GetType().Name}:{ex.Message}";
        }
    }

    private sealed record SilentInstallOptions(
        bool Enabled,
        string? InstallDirectory,
        bool DeploySunbirdSeed)
    {
        public static SilentInstallOptions Parse(string[] args)
        {
            var enabled = false;
            string? installDirectory = null;
            var deploySunbirdSeed = false;

            for (var i = 0; i < args.Length; i += 1)
            {
                var arg = args[i];
                if (arg.Equals("--silent", StringComparison.OrdinalIgnoreCase) ||
                    arg.Equals("/silent", StringComparison.OrdinalIgnoreCase) ||
                    arg.Equals("/S", StringComparison.OrdinalIgnoreCase))
                {
                    enabled = true;
                    continue;
                }

                if (arg.Equals("--sunbird-seed", StringComparison.OrdinalIgnoreCase) ||
                    arg.Equals("/sunbird-seed", StringComparison.OrdinalIgnoreCase))
                {
                    deploySunbirdSeed = true;
                    continue;
                }

                if (arg.Equals("--install-dir", StringComparison.OrdinalIgnoreCase) ||
                    arg.Equals("/install-dir", StringComparison.OrdinalIgnoreCase))
                {
                    if (i + 1 < args.Length)
                    {
                        installDirectory = args[i + 1];
                        i += 1;
                    }
                    continue;
                }

                if (arg.StartsWith("--install-dir=", StringComparison.OrdinalIgnoreCase))
                {
                    installDirectory = arg["--install-dir=".Length..];
                    continue;
                }

                if (arg.StartsWith("/D=", StringComparison.OrdinalIgnoreCase))
                    installDirectory = string.Join(" ", args[i..])["/D=".Length..];
            }

            return new SilentInstallOptions(enabled, installDirectory, deploySunbirdSeed);
        }
    }
}
