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
	"strings"
	"syscall"
	"time"

	"gopkg.in/ini.v1"
)

var (
	baseDir    string
	llmCmd     *exec.Cmd
	backendCmd *exec.Cmd
)

func main() {
	baseDir = getBaseDir()
	logFile := setupLogging()
	defer logFile.Close()

	log.Println("========================================")
	log.Println("  文档解析与合同管理系统 GUI 启动")
	log.Println("========================================")

	// 加载配置
	config := loadLaunchConfig()

	// 启动 LLM 服务
	startLLM(config)

	// 启动后端
	startBackend()

	// 等待后端就绪
	log.Println("等待后端服务就绪...")
	if !waitForService("http://localhost:8000/api/health", 60*time.Second) {
		log.Println("后端启动超时，仍然尝试打开窗口...")
	} else {
		log.Println("后端已就绪")
	}

	// 打开浏览器
	log.Println("打开浏览器...")
	url := fmt.Sprintf("http://localhost:%d", config.ServerPort)
	exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()

	log.Println("系统已启动，关闭此窗口将停止所有服务")
	log.Printf("访问地址: %s", url)

	// 等待信号退出
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	<-sigChan

	// 停止所有服务
	log.Println("收到退出信号，停止服务...")
	stopAll()
	log.Println("已退出")
}

func getBaseDir() string {
	exePath, err := os.Executable()
	if err != nil {
		cwd, _ := os.Getwd()
		return cwd
	}
	return filepath.Dir(exePath)
}

func setupLogging() *os.File {
	logDir := filepath.Join(baseDir, "logs")
	os.MkdirAll(logDir, 0755)

	f, err := os.OpenFile(
		filepath.Join(logDir, "gui_launcher.log"),
		os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644,
	)
	if err != nil {
		return os.Stdout
	}
	multiWriter := io.MultiWriter(os.Stdout, f)
	log.SetOutput(multiWriter)
	log.SetFlags(log.Ldate | log.Ltime)
	return f
}

type LaunchConfig struct {
	LLMCommand string
	LLMPort    int
	ServerPort int
}

func loadLaunchConfig() LaunchConfig {
	config := LaunchConfig{
		LLMPort:    8080,
		ServerPort: 8000,
	}

	configPath := filepath.Join(baseDir, "config", "app.ini")
	cfg, err := ini.Load(configPath)
	if err != nil {
		log.Printf("配置文件加载失败: %v，使用默认配置", err)
		return config
	}

	if cfg.HasSection("llm") {
		llm := cfg.Section("llm")
		config.LLMCommand = llm.Key("launch_command").String()
		config.LLMPort = llm.Key("port").MustInt(8080)
	}
	if cfg.HasSection("server") {
		config.ServerPort = cfg.Section("server").Key("port").MustInt(8000)
	}

	return config
}

func startLLM(config LaunchConfig) {
	if config.LLMCommand == "" {
		log.Println("[LLM] 未配置启动命令，跳过")
		return
	}

	// 替换路径变量
	modelsDir := filepath.Join(baseDir, "models", "llm")
	cmd := config.LLMCommand
	cmd = strings.ReplaceAll(cmd, "{models_dir}", modelsDir)
	cmd = strings.ReplaceAll(cmd, "{base_dir}", baseDir)

	// 解析命令
	parts := splitCommand(cmd)
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

	log.Printf("[LLM] 启动: %s", strings.Join(parts, " "))
	llmCmd = exec.Command(parts[0], parts[1:]...)
	llmCmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000,
	}
	llmCmd.Dir = baseDir

	// 日志输出
	logPath := filepath.Join(baseDir, "logs", "llm.log")
	f, _ := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if f != nil {
		llmCmd.Stdout = f
		llmCmd.Stderr = f
	}

	if err := llmCmd.Start(); err != nil {
		log.Printf("[LLM] 启动失败: %v", err)
		return
	}
	log.Printf("[LLM] 已启动 (PID: %d)", llmCmd.Process.Pid)

	// 等待 LLM 就绪
	llmURL := fmt.Sprintf("http://localhost:%d/health", config.LLMPort)
	if waitForService(llmURL, 30*time.Second) {
		log.Println("[LLM] 服务已就绪")
	} else {
		log.Println("[LLM] 等待超时，继续启动后端...")
	}
}

func startBackend() {
	// 查找 Python
	pythonPath := filepath.Join(baseDir, "runtime", "python", "python.exe")
	if _, err := os.Stat(pythonPath); err != nil {
		pythonPath = "python"
	}

	appScript := filepath.Join(baseDir, "app", "run_backend.py")
	if _, err := os.Stat(appScript); err != nil {
		// 开发环境
		appScript = filepath.Join(baseDir, "run_backend.py")
	}

	log.Printf("[Backend] 启动: %s %s", pythonPath, appScript)

	backendCmd = exec.Command(pythonPath, appScript)
	backendCmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000,
	}
	backendCmd.Dir = filepath.Dir(appScript)

	// 环境变量
	backendCmd.Env = append(os.Environ(),
		"FLAGS_enable_pir_in_executor=0",
		"FLAGS_use_mkldnn=0",
		fmt.Sprintf("PADDLEX_HOME=%s", filepath.Join(baseDir, "models", "paddleocr")),
	)

	logPath := filepath.Join(baseDir, "logs", "backend.log")
	f, _ := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if f != nil {
		backendCmd.Stdout = f
		backendCmd.Stderr = f
	}

	if err := backendCmd.Start(); err != nil {
		log.Printf("[Backend] 启动失败: %v", err)
		return
	}
	log.Printf("[Backend] 已启动 (PID: %d)", backendCmd.Process.Pid)
}

func stopAll() {
	if backendCmd != nil && backendCmd.Process != nil {
		log.Println("停止后端...")
		backendCmd.Process.Kill()
	}
	if llmCmd != nil && llmCmd.Process != nil {
		log.Println("停止 LLM...")
		llmCmd.Process.Kill()
	}
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
		time.Sleep(time.Second)
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
