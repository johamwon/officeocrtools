package main

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/getlantern/systray"
	"golang.org/x/sys/windows/registry"
)

const (
	appName    = "DocParser"
	appTitle   = "文档解析与合同管理系统"
	appVersion = "0.2.0"
	backendURL = "http://localhost:8000"
	llmURL     = "http://localhost:8080"
)

var (
	baseDir    string
	llmCmd     *exec.Cmd
	backendCmd *exec.Cmd
	logFile    *os.File
)

func main() {
	// 确定基础目录
	exePath, err := os.Executable()
	if err != nil {
		log.Fatal(err)
	}
	baseDir = filepath.Dir(exePath)

	// 初始化日志
	setupLogging()
	defer logFile.Close()

	log.Printf("%s v%s 启动中...", appTitle, appVersion)

	// 启动系统托盘
	systray.Run(onReady, onExit)
}

func setupLogging() {
	logDir := filepath.Join(baseDir, "logs")
	os.MkdirAll(logDir, 0755)

	var err error
	logFile, err = os.OpenFile(
		filepath.Join(logDir, "launcher.log"),
		os.O_CREATE|os.O_WRONLY|os.O_APPEND,
		0644,
	)
	if err != nil {
		log.Fatal(err)
	}

	multiWriter := io.MultiWriter(os.Stdout, logFile)
	log.SetOutput(multiWriter)
	log.SetFlags(log.Ldate | log.Ltime | log.Lshortfile)
}

func onReady() {
	// 设置托盘图标和标题
	systray.SetTitle(appName)
	systray.SetTooltip(fmt.Sprintf("%s v%s", appTitle, appVersion))

	// 菜单项
	mOpen := systray.AddMenuItem("打开浏览器", "在浏览器中打开系统")
	mStatus := systray.AddMenuItem("● 启动中...", "服务状态")
	mStatus.Disable()
	systray.AddSeparator()
	mRestart := systray.AddMenuItem("重启服务", "重启所有服务")
	mLogs := systray.AddMenuItem("查看日志", "打开日志目录")
	systray.AddSeparator()
	mAutoStart := systray.AddMenuItemCheckbox("开机自启", "设置开机自动启动", isAutoStartEnabled())
	systray.AddSeparator()
	mQuit := systray.AddMenuItem("退出", "停止所有服务并退出")

	// 启动服务
	go startServices(mStatus)

	// 监听信号
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// 事件循环
	go func() {
		for {
			select {
			case <-mOpen.ClickedCh:
				openBrowser(backendURL)
			case <-mRestart.ClickedCh:
				log.Println("用户请求重启服务...")
				mStatus.SetTitle("● 重启中...")
				stopServices()
				time.Sleep(2 * time.Second)
				go startServices(mStatus)
			case <-mLogs.ClickedCh:
				logDir := filepath.Join(baseDir, "logs")
				exec.Command("explorer", logDir).Start()
			case <-mAutoStart.ClickedCh:
				if mAutoStart.Checked() {
					mAutoStart.Uncheck()
					setAutoStart(false)
					log.Println("已取消开机自启")
				} else {
					mAutoStart.Check()
					setAutoStart(true)
					log.Println("已设置开机自启")
				}
			case <-mQuit.ClickedCh:
				systray.Quit()
			case <-sigChan:
				systray.Quit()
			}
		}
	}()
}

func onExit() {
	log.Println("正在退出...")
	stopServices()
	log.Println("已退出")
}

func startServices(statusItem *systray.MenuItem) {
	// 1. 启动 LLM 服务
	llamaPath := filepath.Join(baseDir, "runtime", "llama-server.exe")
	modelPath := filepath.Join(baseDir, "models", "llm", "qwen2.5-coder-1.5b-instruct-q8_0.gguf")

	if fileExists(llamaPath) && fileExists(modelPath) {
		log.Println("启动 LLM 服务...")
		llmCmd = startHiddenProcess(llamaPath,
			"-m", modelPath,
			"-c", "4096",
			"--port", "8080",
			"--log-disable",
		)

		// 等待 LLM 就绪
		if !waitForService(llmURL+"/health", 30*time.Second) {
			log.Println("⚠ LLM 服务启动超时")
		} else {
			log.Println("✓ LLM 服务已就绪")
		}
	} else {
		log.Println("⚠ 未找到 LLM 运行时，跳过")
	}

	// 2. 启动后端
	pythonPath := filepath.Join(baseDir, "runtime", "python", "python.exe")
	if !fileExists(pythonPath) {
		// 回退到系统Python
		pythonPath = "python"
	}
	appScript := filepath.Join(baseDir, "app", "run_backend.py")

	log.Println("启动后端服务...")
	backendCmd = startHiddenProcess(pythonPath, appScript)

	// 等待后端就绪
	if !waitForService(backendURL+"/api/health", 60*time.Second) {
		log.Println("⚠ 后端服务启动超时")
		statusItem.SetTitle("● 启动失败")
	} else {
		log.Println("✓ 后端服务已就绪")
		statusItem.SetTitle("● 运行中")

		// 首次启动打开浏览器
		openBrowser(backendURL)
	}
}

func stopServices() {
	if backendCmd != nil && backendCmd.Process != nil {
		log.Println("停止后端...")
		backendCmd.Process.Kill()
		backendCmd = nil
	}
	if llmCmd != nil && llmCmd.Process != nil {
		log.Println("停止 LLM...")
		llmCmd.Process.Kill()
		llmCmd = nil
	}
}

func startHiddenProcess(name string, args ...string) *exec.Cmd {
	cmd := exec.Command(name, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000, // CREATE_NO_WINDOW
	}
	cmd.Dir = baseDir

	// 重定向输出到日志
	logPath := filepath.Join(baseDir, "logs", filepath.Base(name)+".log")
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err == nil {
		cmd.Stdout = f
		cmd.Stderr = f
	}

	if err := cmd.Start(); err != nil {
		log.Printf("启动失败 %s: %v", name, err)
		return nil
	}

	log.Printf("已启动 %s (PID: %d)", name, cmd.Process.Pid)
	return cmd
}

func waitForService(url string, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	client := &http.Client{Timeout: 2 * time.Second}

	for time.Now().Before(deadline) {
		resp, err := client.Get(url)
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == 200 {
				return true
			}
		}
		time.Sleep(1 * time.Second)
	}
	return false
}

func openBrowser(url string) {
	exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// ========== 开机自启 ==========

func isAutoStartEnabled() bool {
	key, err := registry.OpenKey(
		registry.CURRENT_USER,
		`Software\Microsoft\Windows\CurrentVersion\Run`,
		registry.QUERY_VALUE,
	)
	if err != nil {
		return false
	}
	defer key.Close()

	_, _, err = key.GetStringValue(appName)
	return err == nil
}

func setAutoStart(enable bool) error {
	key, err := registry.OpenKey(
		registry.CURRENT_USER,
		`Software\Microsoft\Windows\CurrentVersion\Run`,
		registry.ALL_ACCESS,
	)
	if err != nil {
		return err
	}
	defer key.Close()

	if enable {
		exePath, _ := os.Executable()
		return key.SetStringValue(appName, exePath)
	}
	return key.DeleteValue(appName)
}
