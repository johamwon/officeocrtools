package main

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	_ "modernc.org/sqlite"
	"gopkg.in/ini.v1"
)

// Config 应用配置
type Config struct {
	DBPath     string
	WebhookURL string
	Secret     string
	CheckHour  int
	CheckMin   int
}

// Schedule 时间节点
type Schedule struct {
	ID               int
	ContractID       int
	EventType        string
	EventName        string
	EventDate        string
	Amount           sql.NullFloat64
	Description      sql.NullString
	RemindDays       string // JSON array
	LastNotifiedDate sql.NullString
	Status           string
}

// Contract 合同信息
type Contract struct {
	ID           int
	ContractName sql.NullString
	PartyA       sql.NullString
	PartyB       sql.NullString
}

func main() {
	// 确定基础目录（exe所在目录的上一级，或当前目录）
	baseDir := getBaseDir()
	logFile := setupLogging(baseDir)
	defer logFile.Close()

	log.Println("========================================")
	log.Println("  合同节点推送服务启动")
	log.Println("========================================")

	// 加载配置
	config, err := loadConfig(baseDir)
	if err != nil {
		log.Fatalf("加载配置失败: %v", err)
	}

	if config.WebhookURL == "" {
		log.Println("未配置钉钉Webhook地址，服务退出")
		return
	}

	log.Printf("数据库: %s", config.DBPath)
	log.Printf("检查时间: %02d:%02d", config.CheckHour, config.CheckMin)

	// 检查今天是否已执行
	stateFile := filepath.Join(baseDir, "storage", "notify_last_run.txt")
	today := time.Now().Format("2006-01-02")

	if !hasRunToday(stateFile, today) {
		now := time.Now()
		checkTime := time.Date(now.Year(), now.Month(), now.Day(), config.CheckHour, config.CheckMin, 0, 0, now.Location())

		if now.After(checkTime) {
			// 已过检查时间，立即补执行
			log.Println("已过今日检查时间，立即补执行...")
			runCheck(config, stateFile)
		} else {
			// 等到设定时间
			waitDuration := checkTime.Sub(now)
			log.Printf("等待 %v 后执行今日检查...", waitDuration.Round(time.Minute))
			time.Sleep(waitDuration)
			runCheck(config, stateFile)
		}
	} else {
		log.Println("今日已执行过检查，等待明天...")
	}

	// 持续运行，每天定时执行
	for {
		nextRun := getNextRunTime(config.CheckHour, config.CheckMin)
		waitDuration := time.Until(nextRun)
		log.Printf("下次检查: %s (等待 %v)", nextRun.Format("2006-01-02 15:04"), waitDuration.Round(time.Minute))
		time.Sleep(waitDuration)
		runCheck(config, stateFile)
	}
}

func getBaseDir() string {
	exePath, err := os.Executable()
	if err != nil {
		return "."
	}
	exeDir := filepath.Dir(exePath)

	// 如果exe在某个子目录（如runtime/），向上找config/app.ini
	candidates := []string{
		exeDir,
		filepath.Dir(exeDir),
		filepath.Join(exeDir, ".."),
	}

	for _, dir := range candidates {
		if _, err := os.Stat(filepath.Join(dir, "config", "app.ini")); err == nil {
			abs, _ := filepath.Abs(dir)
			return abs
		}
	}

	// 回退到当前工作目录
	cwd, _ := os.Getwd()
	return cwd
}

func setupLogging(baseDir string) *os.File {
	logDir := filepath.Join(baseDir, "logs")
	os.MkdirAll(logDir, 0755)

	logPath := filepath.Join(logDir, "notify_service.log")
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		log.Printf("无法打开日志文件: %v", err)
		return os.Stdout
	}

	// 同时输出到文件和stdout
	multiWriter := io.MultiWriter(os.Stdout, f)
	log.SetOutput(multiWriter)
	log.SetFlags(log.Ldate | log.Ltime)
	return f
}

func loadConfig(baseDir string) (*Config, error) {
	configPath := filepath.Join(baseDir, "config", "app.ini")
	cfg, err := ini.Load(configPath)
	if err != nil {
		return nil, fmt.Errorf("读取配置文件失败 %s: %v", configPath, err)
	}

	notify := cfg.Section("notify")
	config := &Config{
		DBPath:     filepath.Join(baseDir, "storage", "parser.db"),
		WebhookURL: notify.Key("dingtalk_webhook").String(),
		Secret:     notify.Key("dingtalk_secret").String(),
		CheckHour:  notify.Key("check_hour").MustInt(9),
		CheckMin:   notify.Key("check_minute").MustInt(0),
	}

	return config, nil
}

func hasRunToday(stateFile, today string) bool {
	data, err := os.ReadFile(stateFile)
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(data)) == today
}

func markRunToday(stateFile, today string) {
	os.MkdirAll(filepath.Dir(stateFile), 0755)
	os.WriteFile(stateFile, []byte(today), 0644)
}

func getNextRunTime(hour, min int) time.Time {
	now := time.Now()
	next := time.Date(now.Year(), now.Month(), now.Day()+1, hour, min, 0, 0, now.Location())
	return next
}

func runCheck(config *Config, stateFile string) {
	log.Println("开始检查时间节点...")
	today := time.Now().Format("2006-01-02")

	db, err := sql.Open("sqlite", config.DBPath+"?mode=ro&_pragma=journal_mode(WAL)")
	if err != nil {
		log.Printf("打开数据库失败: %v", err)
		return
	}
	defer db.Close()

	// 查询所有待推送的节点
	rows, err := db.Query(`
		SELECT id, contract_id, event_type, event_name, event_date, 
		       amount, description, remind_days, last_notified_date, status
		FROM schedules 
		WHERE status = 'pending' AND event_date IS NOT NULL
		ORDER BY event_date
	`)
	if err != nil {
		log.Printf("查询节点失败: %v", err)
		return
	}
	defer rows.Close()

	sentCount := 0
	for rows.Next() {
		var s Schedule
		err := rows.Scan(&s.ID, &s.ContractID, &s.EventType, &s.EventName,
			&s.EventDate, &s.Amount, &s.Description, &s.RemindDays,
			&s.LastNotifiedDate, &s.Status)
		if err != nil {
			log.Printf("读取行失败: %v", err)
			continue
		}

		// 计算剩余天数
		eventDate, err := time.Parse("2006-01-02", s.EventDate)
		if err != nil {
			continue
		}
		todayDate, _ := time.Parse("2006-01-02", today)
		daysRemaining := int(eventDate.Sub(todayDate).Hours() / 24)

		// 判断是否需要推送
		if !shouldNotify(s, today, daysRemaining) {
			continue
		}

		// 获取合同信息
		contract := getContract(db, s.ContractID)

		// 发送通知
		success := sendNotification(config, s, contract, daysRemaining)
		if success {
			sentCount++
			// 更新数据库
			updateSchedule(db, s.ID, today, daysRemaining)
		}
	}

	log.Printf("检查完成，推送了 %d 条通知", sentCount)
	markRunToday(stateFile, today)
}

func shouldNotify(s Schedule, today string, daysRemaining int) bool {
	// 今天已推送过
	if s.LastNotifiedDate.Valid && s.LastNotifiedDate.String == today {
		return false
	}

	// 解析提醒天数列表
	remindDays := []int{15, 7, 3, 1}
	if s.RemindDays != "" {
		var parsed []int
		if json.Unmarshal([]byte(s.RemindDays), &parsed) == nil && len(parsed) > 0 {
			remindDays = parsed
		}
	}

	// 在提醒天数列表中
	for _, d := range remindDays {
		if daysRemaining == d {
			return true
		}
	}

	// 已逾期：每天推送
	if daysRemaining <= 0 {
		return true
	}

	return false
}

func getContract(db *sql.DB, contractID int) Contract {
	var c Contract
	c.ID = contractID
	db.QueryRow(`SELECT contract_name, party_a, party_b FROM contracts WHERE id = ?`, contractID).
		Scan(&c.ContractName, &c.PartyA, &c.PartyB)
	return c
}

func updateSchedule(db *sql.DB, scheduleID int, today string, daysRemaining int) {
	// 用写模式重新打开（只读模式不能写）
	dbPath := ""
	db.QueryRow("PRAGMA database_list").Scan(nil, nil, &dbPath)

	writeDB, err := sql.Open("sqlite", dbPath+"?_pragma=journal_mode(WAL)")
	if err != nil {
		// 回退：直接用原连接尝试
		writeDB = db
	} else {
		defer writeDB.Close()
	}

	if daysRemaining < -30 {
		writeDB.Exec(`UPDATE schedules SET last_notified_date = ?, status = 'completed' WHERE id = ?`, today, scheduleID)
	} else {
		writeDB.Exec(`UPDATE schedules SET last_notified_date = ? WHERE id = ?`, today, scheduleID)
	}
}

func sendNotification(config *Config, s Schedule, c Contract, daysRemaining int) bool {
	// 构建消息
	message := buildMessage(s, c, daysRemaining)

	// 构建钉钉请求
	payload := map[string]interface{}{
		"msgtype": "markdown",
		"markdown": map[string]string{
			"title": fmt.Sprintf("合同提醒：%s", s.EventName),
			"text":  message,
		},
	}

	jsonData, err := json.Marshal(payload)
	if err != nil {
		log.Printf("JSON序列化失败: %v", err)
		return false
	}

	resp, err := http.Post(config.WebhookURL, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		log.Printf("发送失败: %v", err)
		return false
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	var result map[string]interface{}
	json.Unmarshal(body, &result)

	errcode, _ := result["errcode"].(float64)
	if errcode == 0 {
		log.Printf("✓ 推送成功: %s (%s)", s.EventName, s.EventDate)
		return true
	}

	log.Printf("✗ 推送失败: %v", string(body))
	return false
}

func buildMessage(s Schedule, c Contract, daysRemaining int) string {
	// 紧急程度
	var urgency string
	if daysRemaining <= 0 {
		urgency = "🚨 **已逾期**"
	} else if daysRemaining <= 3 {
		urgency = "⚠️ **紧急**"
	} else if daysRemaining <= 7 {
		urgency = "📢 **即将到期**"
	} else {
		urgency = "📅 **提醒**"
	}

	contractName := "未命名合同"
	if c.ContractName.Valid && c.ContractName.String != "" {
		contractName = c.ContractName.String
	}

	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("## %s 合同节点提醒\n\n", urgency))
	sb.WriteString(fmt.Sprintf("**合同：** %s\n\n", contractName))
	sb.WriteString(fmt.Sprintf("**节点：** %s\n\n", s.EventName))

	if daysRemaining <= 0 {
		sb.WriteString(fmt.Sprintf("**日期：** %s（已逾期 %d 天）\n\n", s.EventDate, -daysRemaining))
	} else {
		sb.WriteString(fmt.Sprintf("**日期：** %s（还剩 %d 天）\n\n", s.EventDate, daysRemaining))
	}

	if s.Amount.Valid && s.Amount.Float64 > 0 {
		sb.WriteString(fmt.Sprintf("**金额：** ¥%s\n\n", formatAmount(s.Amount.Float64)))
	}
	if c.PartyA.Valid && c.PartyA.String != "" {
		sb.WriteString(fmt.Sprintf("**甲方：** %s\n\n", c.PartyA.String))
	}
	if c.PartyB.Valid && c.PartyB.String != "" {
		sb.WriteString(fmt.Sprintf("**乙方：** %s\n\n", c.PartyB.String))
	}
	if s.Description.Valid && s.Description.String != "" {
		sb.WriteString(fmt.Sprintf("> %s\n\n", s.Description.String))
	}

	sb.WriteString("---\n\n请相关人员关注并及时处理。")
	return sb.String()
}

func formatAmount(amount float64) string {
	s := strconv.FormatFloat(amount, 'f', 2, 64)
	// 添加千分位
	parts := strings.Split(s, ".")
	intPart := parts[0]
	var result []byte
	for i, c := range intPart {
		if i > 0 && (len(intPart)-i)%3 == 0 {
			result = append(result, ',')
		}
		result = append(result, byte(c))
	}
	return string(result) + "." + parts[1]
}
