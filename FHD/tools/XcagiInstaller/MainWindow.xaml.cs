using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media.Imaging;
using XcagiInstaller.Services;

namespace XcagiInstaller;

public partial class MainWindow : Window
{
    private enum WizardStep
    {
        Welcome,
        License,
        Directory,
        Installing,
        Complete,
        Error,
    }

    private WizardStep _step = WizardStep.Welcome;
    private string? _setupExePath;
    private bool _hasEmbeddedPayload;
    private string _installDir = NsisSilentInstaller.DefaultInstallDirectory();
    private string? _installedAppExe;
    private CancellationTokenSource? _installCts;

    private const double ExtractPhaseMax = 12;

    public MainWindow()
    {
        InitializeComponent();
        Loaded += MainWindow_OnLoaded;
        WelcomeAgreeCheck.Checked += SyncAgreeFromWelcome;
        WelcomeAgreeCheck.Unchecked += SyncAgreeFromWelcome;
        AgreeLicenseCheck.Checked += SyncAgreeFromLicense;
        AgreeLicenseCheck.Unchecked += SyncAgreeFromLicense;
    }

    private void MainWindow_OnLoaded(object sender, RoutedEventArgs e)
    {
        LoadLogo();
        var version = typeof(MainWindow).Assembly.GetName().Version?.ToString() ?? "unknown";
        WelcomeSubtitleText.Text = $"{version} · 企业 AI 员工宿主";
        InstallDirBox.Text = _installDir;
        WelcomePathPreview.Text = _installDir;

        var license = LicenseTextProvider.Load();
        LicenseTextBlock.Text = string.IsNullOrWhiteSpace(license)
            ? "（协议全文未内嵌）"
            : license.Length > 10000
                ? license[..10000] + "\n\n…"
                : license;

        _hasEmbeddedPayload = EmbeddedPayloadExtractor.HasEmbeddedPayload();
        if (!_hasEmbeddedPayload)
        {
            _setupExePath = PayloadLocator.FindSetupExeOnDisk(version);
            if (_setupExePath == null)
            {
                ShowError(
                    "未找到安装包。\n\n" +
                    "请使用完整发行包（build-installer.ps1 生成），\n" +
                    $"或将 XCAGI-Setup-{version}-x64.exe 置于本程序同目录。");
                return;
            }
        }

        ApplyStepUi();
        if (SunbirdSeedExtractor.HasEmbeddedSeed())
        {
            FetchSunbirdDataCheck.Visibility = Visibility.Visible;
            Title = "太阳鸟 PRO";
            WelcomeSubtitleText.Text = "10.0 · 太阳鸟考勤定制安装";
        }
    }

    private void SyncAgreeFromWelcome(object sender, RoutedEventArgs e)
    {
        AgreeLicenseCheck.IsChecked = WelcomeAgreeCheck.IsChecked;
        UpdateWelcomeButtonState();
    }

    private void SyncAgreeFromLicense(object sender, RoutedEventArgs e)
    {
        WelcomeAgreeCheck.IsChecked = AgreeLicenseCheck.IsChecked;
        UpdateWelcomeButtonState();
        if (_step == WizardStep.License)
            NextButton.IsEnabled = AgreeLicenseCheck.IsChecked == true;
    }

    private void UpdateWelcomeButtonState()
    {
        if (_step == WizardStep.Welcome)
            NextButton.IsEnabled = WelcomeAgreeCheck.IsChecked == true;
    }

    private void LoadLogo()
    {
        try
        {
            LogoImage.Source = new BitmapImage(new Uri("pack://application:,,,/Assets/logo.png", UriKind.Absolute));
        }
        catch
        {
            LogoImage.Visibility = Visibility.Collapsed;
        }
    }

    private void WindowDrag_OnMouseDown(object sender, MouseButtonEventArgs e)
    {
        if (e.LeftButton == MouseButtonState.Pressed)
            DragMove();
    }

    private void ViewLicense_OnClick(object sender, RoutedEventArgs e)
    {
        _step = WizardStep.License;
        ApplyStepUi();
    }

    private void CustomizePath_OnClick(object sender, RoutedEventArgs e)
    {
        _step = WizardStep.Directory;
        ApplyStepUi();
    }

    private void ApplyStepUi()
    {
        WelcomePanel.Visibility = _step == WizardStep.Welcome ? Visibility.Visible : Visibility.Collapsed;
        LicensePanel.Visibility = _step == WizardStep.License ? Visibility.Visible : Visibility.Collapsed;
        DirectoryPanel.Visibility = _step == WizardStep.Directory ? Visibility.Visible : Visibility.Collapsed;
        InstallingPanel.Visibility = _step == WizardStep.Installing ? Visibility.Visible : Visibility.Collapsed;
        CompletePanel.Visibility = _step == WizardStep.Complete ? Visibility.Visible : Visibility.Collapsed;
        ErrorPanel.Visibility = _step == WizardStep.Error ? Visibility.Visible : Visibility.Collapsed;

        BackButton.Visibility = _step is WizardStep.License or WizardStep.Directory
            ? Visibility.Visible
            : Visibility.Collapsed;

        CancelButton.Visibility = _step is WizardStep.Complete or WizardStep.Error
            ? Visibility.Collapsed
            : Visibility.Visible;
        CancelButton.IsEnabled = _step != WizardStep.Installing;

        NextButton.Style = (Style)FindResource(
            _step == WizardStep.Complete ? "SuccessButtonStyle" : "HeroButtonStyle");

        switch (_step)
        {
            case WizardStep.Welcome:
                NextButton.Content = "继续";
                UpdateWelcomeButtonState();
                break;
            case WizardStep.License:
                NextButton.Content = "继续";
                NextButton.IsEnabled = AgreeLicenseCheck.IsChecked == true;
                break;
            case WizardStep.Directory:
                NextButton.Content = "安装";
                NextButton.IsEnabled = !string.IsNullOrWhiteSpace(InstallDirBox.Text);
                break;
            case WizardStep.Installing:
                NextButton.IsEnabled = false;
                BackButton.Visibility = Visibility.Collapsed;
                break;
            case WizardStep.Complete:
                NextButton.Content = "好";
                NextButton.IsEnabled = true;
                break;
            case WizardStep.Error:
                NextButton.Content = "好";
                NextButton.IsEnabled = true;
                break;
        }

        UpdateStepRails();
    }

    private void UpdateStepRails()
    {
        var dots = new[] { Dot1, Dot2, Dot3, Dot4, Dot5 };
        var idx = _step switch
        {
            WizardStep.Welcome => 0,
            WizardStep.License => 1,
            WizardStep.Directory => 2,
            WizardStep.Installing => 3,
            WizardStep.Complete => 4,
            _ => 0,
        };

        var active = FindResource("DotActive") as System.Windows.Media.Brush;
        var inactive = FindResource("DotInactive") as System.Windows.Media.Brush;
        for (var i = 0; i < dots.Length; i++)
        {
            dots[i].Fill = i == idx && _step != WizardStep.Error ? active : inactive;
            dots[i].Width = i == idx && _step != WizardStep.Error ? 7 : 6;
            dots[i].Height = dots[i].Width;
        }
    }

    private void BrowseDir_OnClick(object sender, RoutedEventArgs e)
    {
        using var dialog = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = "选择安装目录",
            SelectedPath = InstallDirBox.Text,
            ShowNewFolderButton = true,
        };
        if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK)
        {
            InstallDirBox.Text = dialog.SelectedPath;
            WelcomePathPreview.Text = dialog.SelectedPath;
        }
    }

    private async void Next_OnClick(object sender, RoutedEventArgs e)
    {
        switch (_step)
        {
            case WizardStep.Welcome:
                if (WelcomeAgreeCheck.IsChecked != true)
                    return;
                _step = WizardStep.Directory;
                ApplyStepUi();
                break;
            case WizardStep.License:
                if (AgreeLicenseCheck.IsChecked != true)
                    return;
                _step = WizardStep.Directory;
                ApplyStepUi();
                break;
            case WizardStep.Directory:
                _installDir = InstallDirBox.Text.Trim();
                WelcomePathPreview.Text = _installDir;
                await RunInstallAsync();
                break;
            case WizardStep.Complete:
                Close();
                break;
            case WizardStep.Error:
                Close();
                break;
        }
    }

    private void Back_OnClick(object sender, RoutedEventArgs e)
    {
        _step = _step switch
        {
            WizardStep.License => WizardStep.Welcome,
            WizardStep.Directory => WizardStep.Welcome,
            _ => _step,
        };
        ApplyStepUi();
    }

    private void Cancel_OnClick(object sender, RoutedEventArgs e)
    {
        if (_step == WizardStep.Installing)
            return;
        Close();
    }

    private void Close_OnClick(object sender, RoutedEventArgs e) => Close();

    private async Task RunInstallAsync()
    {
        _step = WizardStep.Installing;
        ApplyStepUi();
        _installCts = new CancellationTokenSource();

        BeginInstallProgressUi();

        if (string.IsNullOrEmpty(_setupExePath))
        {
            var extractProgress = new Progress<double>(p =>
            {
                var overall = p * ExtractPhaseMax / 100.0;
                UpdateInstallProgress(overall, DescribeExtractStatus(p));
            });

            try
            {
                _setupExePath = await PayloadLocator.ResolveSetupExeAsync(extractProgress, _installCts.Token);
            }
            catch (OperationCanceledException)
            {
                ShowError("已取消");
                return;
            }
            catch (Exception ex)
            {
                ShowError(ex.Message);
                return;
            }

            if (string.IsNullOrEmpty(_setupExePath))
            {
                ShowError("无法准备安装包");
                return;
            }
        }
        else
        {
            UpdateInstallProgress(ExtractPhaseMax, "准备开始安装…");
        }

        var installProgress = new Progress<InstallProgressUpdate>(u =>
        {
            var overall = ExtractPhaseMax + Math.Min(u.Percent, 98) * (100 - ExtractPhaseMax) / 100.0;
            UpdateInstallProgress(overall, u.Percent == 100 ? "本体安装完成，正在准备收尾…" : u.Status);
        });

        var result = await NsisSilentInstaller.RunAsync(
            _setupExePath,
            _installDir,
            installProgress,
            _installCts.Token);

        if (!result.Success)
        {
            ShowError(result.Error ?? "安装失败");
            return;
        }

        _installedAppExe = result.AppExePath;
        var sunbirdNote = "";
        if (FetchSunbirdDataCheck.IsChecked == true && SunbirdSeedExtractor.HasEmbeddedSeed())
        {
            UpdateInstallProgress(94, "正在写入太阳鸟业务数据…");
            try
            {
                var sunbirdProgress = new Progress<string>(msg => UpdateInstallProgress(96, msg));
                var deployed = await SunbirdSeedExtractor.DeployToUserDataAsync(
                    progress: sunbirdProgress,
                    cancellationToken: _installCts.Token).ConfigureAwait(true);
                sunbirdNote = deployed ? "已获取太阳鸟业务数据" : "太阳鸟业务数据未写入";
            }
            catch (Exception ex)
            {
                sunbirdNote = $"业务数据获取失败：{ex.Message}";
            }
        }

        UpdateInstallProgress(99, "正在完成快捷方式与启动设置…");
        var desktopShortcut = DesktopShortcutCheck.IsChecked == true;
        var runAfterInstall = RunAfterInstallCheck.IsChecked == true;
        string extras;
        try { extras = await PostInstallTasks.RunAsync(() => ApplyPostInstallTasks(_installedAppExe, desktopShortcut, runAfterInstall, sunbirdNote)); }
        catch (Exception ex) { ShowError(ex.Message); return; }
        UpdateInstallProgress(100, "安装完成");
        CompletePathText.Text = result.InstallDir ?? "";
        CompleteExtrasText.Text = extras;
        _step = WizardStep.Complete;
        ApplyStepUi();
    }

    private static string ApplyPostInstallTasks(string? installedAppExe, bool desktopShortcut, bool runAfterInstall, string? sunbirdNote)
    {
        if (string.IsNullOrEmpty(installedAppExe))
            return sunbirdNote ?? "";

        var notes = new List<string>();
        if (!string.IsNullOrWhiteSpace(sunbirdNote))
            notes.Add(sunbirdNote);

        if (desktopShortcut)
        {
            if (PostInstallTasks.TryCreateDesktopShortcut(installedAppExe))
                notes.Add("已创建桌面快捷方式");
            else
                notes.Add("桌面快捷方式创建失败");
        }

        PostInstallTasks.TryCreateStartMenuShortcut(installedAppExe);

        if (runAfterInstall)
        {
            try
            {
                PostInstallTasks.TryLaunchApp(installedAppExe);
                notes.Add("已启动 XCAGI");
            }
            catch (Exception ex)
            {
                notes.Add($"启动失败：{ex.Message}");
            }
        }

        return string.Join(" · ", notes);
    }

    private void BeginInstallProgressUi()
    {
        InstallProgress.IsIndeterminate = false;
        InstallProgress.Value = 0;
        InstallPercentText.Visibility = Visibility.Visible;
        InstallPercentText.Text = "0%";
        InstallStatusText.Text = "准备中…";
    }

    private void UpdateInstallProgress(double percent, string status)
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.Invoke(() => UpdateInstallProgress(percent, status));
            return;
        }

        var clamped = Math.Clamp(percent, 0, 100);
        InstallProgress.Value = Math.Max(InstallProgress.Value, clamped);
        InstallPercentText.Text = $"{InstallProgress.Value:0}%";
        InstallStatusText.Text = status;
    }

    private static string DescribeExtractStatus(double extractPercent) =>
        extractPercent switch
        {
            < 25 => "正在解压安装包…",
            < 70 => "正在校验安装文件…",
            < 99 => "即将开始安装…",
            _ => "准备开始安装…",
        };

    private void ShowError(string message)
    {
        NsisSilentInstaller.Trace("GUI install failed: " + message);
        ErrorMessageText.Text = message;
        _step = WizardStep.Error;
        ApplyStepUi();
    }

    protected override void OnClosed(EventArgs e)
    {
        _installCts?.Cancel();
        base.OnClosed(e);
    }
}
