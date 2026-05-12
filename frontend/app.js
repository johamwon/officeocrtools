/**
 * 文档解析与合同管理系统 - 前端主逻辑
 */
const { createApp, ref, reactive, computed, onMounted, onUnmounted } = Vue;

// 字段配置（按文档类型）
const FIELD_CONFIGS = {
    contract: {
        contract_name: { label: '合同名称', multiline: false },
        contract_number: { label: '合同编号', multiline: false },
        party_a: { label: '甲方', multiline: false },
        party_b: { label: '乙方', multiline: false },
        sign_date: { label: '签订日期', multiline: false },
        total_amount: { label: '合同金额', multiline: false },
        service_content: { label: '服务内容', multiline: true },
        performance_period: { label: '履行期限/交付周期', multiline: true },
        payment_terms: { label: '付款方式和条件', multiline: true },
    },
    invoice: {
        invoice_code: { label: '发票代码', multiline: false },
        invoice_number: { label: '发票号码', multiline: false },
        date: { label: '开票日期', multiline: false },
        total_amount: { label: '合计金额', multiline: false },
        tax_amount: { label: '税额', multiline: false },
        total_with_tax: { label: '价税合计', multiline: false },
        seller_name: { label: '销售方', multiline: false },
        buyer_name: { label: '购买方', multiline: false },
    },
    id_card: {
        name: { label: '姓名', multiline: false },
        gender: { label: '性别', multiline: false },
        ethnicity: { label: '民族', multiline: false },
        birth_date: { label: '出生日期', multiline: false },
        address: { label: '住址', multiline: true },
        id_number: { label: '身份证号', multiline: false },
    },
    business_license: {
        company_name: { label: '企业名称', multiline: false },
        credit_code: { label: '统一社会信用代码', multiline: false },
        legal_person: { label: '法定代表人', multiline: false },
        registered_capital: { label: '注册资本', multiline: false },
        establishment_date: { label: '成立日期', multiline: false },
        business_scope: { label: '经营范围', multiline: true },
        address: { label: '住所', multiline: true },
    },
    receipt: {
        merchant_name: { label: '商户名称', multiline: false },
        date: { label: '日期', multiline: false },
        total_amount: { label: '总金额', multiline: false },
        payment_method: { label: '支付方式', multiline: false },
    },
};

const DOC_TYPE_LABELS = {
    contract: '合同',
    invoice: '发票',
    id_card: '身份证',
    business_license: '营业执照',
    receipt: '收据',
};

const STATUS_LABELS = {
    pending: '待处理',
    processing: '处理中',
    completed: '已完成',
    failed: '失败',
    reviewed: '已复审',
};

const STATUS_TYPES = {
    pending: 'info',
    processing: 'warning',
    completed: 'success',
    failed: 'danger',
    reviewed: '',
};

const app = createApp({
    setup() {
        // ========== 状态 ==========
        const activeMenu = ref('upload');

        // 上传
        const uploadForm = reactive({
            docType: 'contract',
            file: null,
        });
        const fileList = ref([]);
        const uploading = ref(false);

        // 任务列表
        const tasks = ref([]);
        const loadingTasks = ref(false);
        const taskFilter = reactive({
            status: null,
        });
        let pollTimer = null;

        // 合同列表
        const contracts = ref([]);
        const loadingContracts = ref(false);
        const contractSearch = ref('');

        // 复审弹窗
        const reviewDialog = reactive({
            visible: false,
            task: null,
            fields: {},
            fieldsDetail: null,
            reviewer: '',
            notes: '',
        });
        const submittingReview = ref(false);

        // 合同详情弹窗
        const contractDialog = reactive({
            visible: false,
            contract: null,
        });

        // ========== 方法 ==========

        const handleMenuSelect = (key) => {
            activeMenu.value = key;
            if (key === 'tasks') {
                loadTasks();
                startPolling();
            } else {
                stopPolling();
            }
            if (key === 'contracts') {
                loadContracts();
            }
        };

        const handleFileChange = (file) => {
            uploadForm.file = file.raw;
        };

        const submitUpload = async () => {
            if (!uploadForm.file || !uploadForm.docType) {
                ElementPlus.ElMessage.warning('请选择文件和文档类型');
                return;
            }

            const formData = new FormData();
            formData.append('file', uploadForm.file);
            formData.append('doc_type', uploadForm.docType);

            uploading.value = true;
            try {
                const res = await axios.post('/api/upload', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                });
                ElementPlus.ElMessage.success(`上传成功！任务ID: ${res.data.task_id}，跳转到任务列表查看进度`);
                fileList.value = [];
                uploadForm.file = null;
                activeMenu.value = 'tasks';
                await loadTasks();
                startPolling();
            } catch (err) {
                const msg = err.response?.data?.detail || err.message;
                ElementPlus.ElMessage.error(`上传失败: ${msg}`);
            } finally {
                uploading.value = false;
            }
        };

        // ========== 任务相关 ==========

        const loadTasks = async () => {
            loadingTasks.value = true;
            try {
                const params = {};
                if (taskFilter.status) params.status = taskFilter.status;
                const res = await axios.get('/api/tasks', { params });
                tasks.value = res.data;
            } catch (err) {
                ElementPlus.ElMessage.error('加载任务列表失败');
            } finally {
                loadingTasks.value = false;
            }
        };

        const startPolling = () => {
            stopPolling();
            pollTimer = setInterval(() => {
                const processingTasks = tasks.value.filter(
                    t => t.status === 'pending' || t.status === 'processing'
                );
                if (processingTasks.length > 0) {
                    loadTasks();
                } else {
                    // 没有处理中的任务，停止轮询
                    stopPolling();
                }
            }, 5000);  // 5秒间隔（降低服务器压力）
        };

        const stopPolling = () => {
            if (pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        };

        const deleteTask = async (task) => {
            try {
                await ElementPlus.ElMessageBox.confirm(
                    `确定删除任务「${task.file_name}」？`,
                    '确认删除',
                    { type: 'warning' }
                );
                await axios.delete(`/api/tasks/${task.id}`);
                ElementPlus.ElMessage.success('已删除');
                await loadTasks();
            } catch (err) {
                if (err !== 'cancel') {
                    ElementPlus.ElMessage.error('删除失败');
                }
            }
        };

        // ========== 复审相关 ==========

        const openReview = async (task) => {
            try {
                const res = await axios.get(`/api/tasks/${task.id}/result`);
                const taskDetail = res.data;
                const result = taskDetail.raw_result || {};

                reviewDialog.task = taskDetail;
                reviewDialog.fields = { ...(result.fields || {}) };
                reviewDialog.fieldsDetail = result.fields_detail || null;
                reviewDialog.reviewer = '';
                reviewDialog.notes = '';
                reviewDialog.visible = true;
            } catch (err) {
                ElementPlus.ElMessage.error('加载任务结果失败');
            }
        };

        const getFieldsForDocType = (docType) => {
            return FIELD_CONFIGS[docType] || {};
        };

        const getFieldDetail = (fieldKey) => {
            if (!reviewDialog.fieldsDetail) return null;
            return reviewDialog.fieldsDetail[fieldKey] || null;
        };

        const confidenceTagType = (confidence) => {
            if (confidence >= 0.9) return 'success';
            if (confidence >= 0.7) return 'warning';
            return 'danger';
        };

        const isPdfFile = (fileName) => {
            return fileName && fileName.toLowerCase().endsWith('.pdf');
        };

        const submitReview = async () => {
            if (!reviewDialog.task) return;

            const docType = reviewDialog.task.doc_type;

            if (docType === 'contract') {
                // 合同入库
                const payload = {
                    task_id: reviewDialog.task.id,
                    reviewer: reviewDialog.reviewer || null,
                    review_notes: reviewDialog.notes || null,
                    ...normalizeFields(reviewDialog.fields, docType),
                };

                submittingReview.value = true;
                try {
                    await axios.post('/api/contracts', payload);
                    ElementPlus.ElMessage.success('合同已入库');
                    reviewDialog.visible = false;
                    await loadTasks();
                } catch (err) {
                    const msg = err.response?.data?.detail || err.message;
                    ElementPlus.ElMessage.error(`入库失败: ${JSON.stringify(msg)}`);
                } finally {
                    submittingReview.value = false;
                }
            } else {
                // 非合同类型：暂时只是标记任务为 reviewed
                ElementPlus.ElMessage.info('非合同类型暂未实现入库功能，仅保留复审记录');
                reviewDialog.visible = false;
            }
        };

        const normalizeFields = (fields, docType) => {
            const result = {};
            const config = FIELD_CONFIGS[docType] || {};

            for (const [key, val] of Object.entries(fields)) {
                if (val === undefined || val === '' || val === null) {
                    result[key] = null;
                    continue;
                }

                // 合同特殊字段处理
                if (docType === 'contract') {
                    if (key === 'total_amount') {
                        // 提取数字
                        const num = parseFloat(String(val).replace(/[^\d.]/g, ''));
                        result[key] = isNaN(num) ? null : num;
                    } else if (key === 'sign_date') {
                        // 规范化为 YYYY-MM-DD
                        result[key] = normalizeDate(val);
                    } else if (key in config) {
                        result[key] = String(val);
                    } else {
                        // 未识别字段放到 extra_fields
                        result.extra_fields = result.extra_fields || {};
                        result.extra_fields[key] = val;
                    }
                } else {
                    result[key] = val;
                }
            }

            return result;
        };

        const normalizeDate = (value) => {
            if (!value) return null;
            const str = String(value).trim();
            // 匹配 YYYY-MM-DD / YYYY/MM/DD / YYYY年MM月DD日 / YYYY.MM.DD
            const m = str.match(/(\d{4})[-\/年.](\d{1,2})[-\/月.](\d{1,2})/);
            if (!m) return null;
            const y = m[1];
            const mo = m[2].padStart(2, '0');
            const d = m[3].padStart(2, '0');
            return `${y}-${mo}-${d}`;
        };

        // ========== 合同相关 ==========

        const loadContracts = async () => {
            loadingContracts.value = true;
            try {
                const params = {};
                if (contractSearch.value) params.keyword = contractSearch.value;
                const res = await axios.get('/api/contracts', { params });
                contracts.value = res.data;
            } catch (err) {
                ElementPlus.ElMessage.error('加载合同列表失败');
            } finally {
                loadingContracts.value = false;
            }
        };

        const viewContract = async (contract) => {
            try {
                const res = await axios.get(`/api/contracts/${contract.id}`);
                contractDialog.contract = res.data;
                contractDialog.visible = true;
            } catch (err) {
                ElementPlus.ElMessage.error('加载合同详情失败');
            }
        };

        const deleteContract = async (contract) => {
            try {
                await ElementPlus.ElMessageBox.confirm(
                    `确定删除合同「${contract.contract_name || contract.id}」？`,
                    '确认删除',
                    { type: 'warning' }
                );
                await axios.delete(`/api/contracts/${contract.id}`);
                ElementPlus.ElMessage.success('已删除');
                await loadContracts();
            } catch (err) {
                if (err !== 'cancel') {
                    ElementPlus.ElMessage.error('删除失败');
                }
            }
        };

        // ========== 辅助方法 ==========

        const docTypeLabel = (type) => DOC_TYPE_LABELS[type] || type;
        const statusLabel = (status) => STATUS_LABELS[status] || status;
        const statusType = (status) => STATUS_TYPES[status] || '';

        const formatDate = (dateStr) => {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            if (isNaN(d.getTime())) return dateStr;
            const pad = (n) => String(n).padStart(2, '0');
            return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
        };

        // ========== 生命周期 ==========

        onMounted(() => {
            // 默认加载任务列表（后台预取）
            loadTasks();
        });

        onUnmounted(() => {
            stopPolling();
        });

        return {
            // 状态
            activeMenu,
            uploadForm,
            fileList,
            uploading,
            tasks,
            loadingTasks,
            taskFilter,
            contracts,
            loadingContracts,
            contractSearch,
            reviewDialog,
            submittingReview,
            contractDialog,
            // 方法
            handleMenuSelect,
            handleFileChange,
            submitUpload,
            loadTasks,
            deleteTask,
            openReview,
            getFieldsForDocType,
            getFieldDetail,
            confidenceTagType,
            isPdfFile,
            submitReview,
            loadContracts,
            viewContract,
            deleteContract,
            docTypeLabel,
            statusLabel,
            statusType,
            formatDate,
            // 图标
            Refresh: ElementPlusIconsVue.Refresh,
        };
    }
});

app.use(ElementPlus);
// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(key, component);
}

app.mount('#app');
