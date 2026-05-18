package main

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/jchv/go-webview2"
	"gopkg.in/ini.v1"
)

var (
	baseDir    string
	llmCmd     *exec.Cmd
	backendCmd *exec.Cmd
)

func main() {
	baseDir = getBaseDir()
	setupLogging()

	log.Println("========================================")
	log.Println("  文档解析系统 GUI 启动")
	log.Println("========================================")

	// 启动后端服务
	startServices()

	// 等待后端就绪
	log.Println("等待后端服务就绪...")
	if !waitForService("http://localhost:8000/api/health", 60*time.Second) {
		log.Println("后端启动超时，仍然尝试打开窗口...")
	} else {
		log.Println("后端已就绪")
	}

	// 打开 WebView2 窗口
	log.Println("打开主窗口...")
	w := webview2.NewWithOptions(webview2.WebViewOptions{
		Debug:     false,
		AutoFocus: true,
		WindowOptions: webview2.WindowOptions{
			Title:  "文档解析与合同管理系统",
			Width:  1400,
			Height: 900,
			IconId: 2,
			Center: true,
		},
	})
	if w == nil {
		log.Fatal("无法创建窗口（需要 WebView2 Runtime）")
	}
	defer w.Destroy()

	w.SetTitle("文档解析与合同管理系统")
	w.SetSize(1400, 900, webview2.HintNone)
	w.Navigate("http://localhost:8000")
	w.Run()

	// 窗口关闭后停止服务
	log.Println("窗口关闭，停止服务...")
	stopServices()
	log.Println("已退出")
}

func getBaseDir() string {
	exePath, err := os.Executable()
	if err != nil {
		cwd, _ := os.Getwd()
		return cwd
	}
	exeDir := filepath.Dir(exePath)

	// 查找 config/app.ini 确定根目录
	candidates := []string{exeDir, filepath.Dir(exeDir)}
	for _, dir := range candidates {
		if _, err := os.Stat(filepath.Join(dir, "config", "app.ini")); err == nil {
			abs, _ := filepath.Abs(dir)
			return abs
		}
	}
	return exeDir
}

func setupLogging() {
	logDir := filepath.Join(baseDir, "logs")
	os.MkdirAll(logDir, 0755)

	logPath := filepath.Join(logDir, "gui_launcher.log")
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return
	}
	log.SetOutput(io.MultiWriter(os.Stdout, f))
	log.SetFlags(log.Ldate | log.Ltime)
}

func startServices() {
	// 1. 启动 LLM
	startLLM()

	// 2. 启动后端
	startBackend()
}

func startLLM() {
	configPath := filepath.Join(baseDir, "config", "app.ini")
	cfg, err := ini.Load(configPath)
	if err != nil {
		log.Printf("读取配置失败: %v", err)
		return
	}

	launchCmd := cfg.Section("llm").Key("launch_command").String()
	if launchCmd == "" {
		log.Println("LLM: 未配置启动命令，跳过")
		return
	}

	// 替换路径变量
	modelsDir := filepath.Join(baseDir, "models", "llm")
	launchCmd = strings.ReplaceAll(launchCmd, "{models_dir}", modelsDir)
	launchCmd = strings.ReplaceAll(launchCmd, "{base_dir}", baseDir)

	// 解析命令
	parts := splitCommand(launchCmd)
	if len(parts) == 0 {
		return
	}

	// 检查 llama-server 是否在 runtime 目录
	exeName := parts[0]
	runtimeExe := filepath.Join(baseDir, "runtime", exeName)
	if _, err := os.Stat(runtimeExe); err == nil {
		parts[0] = runtimeExe
	} else if _, err := os.Stat(runtimeExe + ".exe"); err == nil {
		parts[0] = runtimeExe + ".exe"
	}

	log.Printf("LLM: 启动 %s", parts[0])
	llmCmd = startHiddenProcess(parts[0], parts[1:]...)

	// 等待 LLM 就绪
	llmPort := cfg.Section("llm").Key("port").MustString("8080")
	healthURL := fmt.Sprintf("http://localhost:%s/health", llmPort)
	if waitForService(healthURL, 15*time.Second) {
		log.Println("LLM: 已就绪")
	} else {
		log.Println("LLM: 启动中（可能需要更多时间）")
	}
}

func startBackend() {
	pythonExe := filepath.Join(baseDir, "runtime", "python", "python.exe")
	if _, err := os.Stat(pythonExe); err != nil {
		// 回退到系统 Python
		pythonExe = "python"
	}

	appScript := filepath.Join(baseDir, "app", "run_backend.py")
	if _, err := os.Stat(appScript); err != nil {
		// 开发环境
		appScript = filepath.Join(baseDir, "run_backend.py")
	}

	log.Printf("Backend: 启动 %s %s", pythonExe, appScript)

	cmd := exec.Command(pythonExe, appScript)
	cmd.Dir = filepath.Dir(appScript)
	cmd.Env = append(os.Environ(),
		"FLAGS_enable_pir_in_executor=0",
		"FLAGS_use_mkldnn=0",
		fmt.Sprintf("PADDLEX_HOME=%s", filepath.Join(baseDir, "models", "paddleocr")),
	)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000, // CREATE_NO_WINDOW
	}

	// 日志输出
	logPath := filepath.Join(baseDir, "logs", "backend_stdout.log")
	logFile, _ := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if logFile != nil {
		cmd.Stdout = logFile
		cmd.Stderr = logFile
	}

	if err := cmd.Start(); err != nil {
		log.Printf("Backend: 启动失败: %v", err)
		return
	}
	backendCmd = cmd
	log.Printf("Backend: PID %d", cmd.Process.Pid)
}

func stopServices() {
	if backendCmd != nil && backendCmd.Process != nil {
		log.Println("停止后端...")
		backendCmd.Process.Kill()
	}
	if llmCmd != nil && llmCmd.Process != nil {
		log.Println("停止 LLM...")
		llmCmd.Process.Kill()
	}
}

func startHiddenProcess(name string, args ...string) *exec.Cmd {
	cmd := exec.Command(name, args...)
	cmd.Dir = baseDir
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000,
	}

	logPath := filepath.Join(baseDir, "logs", "llm_stdout.log")
	f, _ := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if f != nil {
		cmd.Stdout = f
		cmd.Stderr = f
	}

	if err := cmd.Start(); err != nil {
		log.Printf("启动失败 %s: %v", name, err)
		return nil
	}
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

func splitCommand(cmd string) []string {
	// 简单的命令行分割（支持引号）
	var parts []string
	var current strings.Builder
	inQuote := false

	for _, c := range cmd {
		switch {
		case c == '"':
			inQuote = !inQuote
		case c == ' ' && !inQuote:
			if current.Len() > 0 {
				parts = append(parts, current.String())
				current.Reset()
			}
		default:
			current.WriteRune(c)
		}
	}
	if current.Len() > 0 {
		parts = append(parts, current.String())
	}
	return parts
}
