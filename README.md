# Munjiz OS Controller (`munjiz-os-controller`) — v2.0

محرك توجيه هجين ثلاثي الطبقات (3-Layer Context-Aware Hybrid Execution Engine) وخادم بروتوكول سياق النماذج (MCP Server) مصمم خصيصاً لتمكين وكلاء تطبيق **مُنجز (Munjiz)** من التحكم الكامل والبصري في نظام التشغيل Windows والويب، مع تتبع حي لمؤشر الفأرة ودعم أصلي للكتابة باللغة العربية.

يستلهم هذا المشروع معماريته الهندسية من أقوى الأطر البحثية والعملية مفتوحة المصدر ليتجاوز قيود مشاريع النقر البصري التقليدية مثل [Open Computer Use](https://github.com/ifuryst/open-computer-use) و[Self-Operating Computer](https://github.com/othersideai/self-operating-computer)، جامعاً بين واجهة الوكيل والحاسوب في [Simular AI Agent-S](https://github.com/simular-ai/agent-s) ونظام الوكلاء الهجين لبيئة ويندوز في [Microsoft UFO](https://github.com/microsoft/ufo) ومحرك الرؤية وتحليل عناصر الشاشة [Microsoft OmniParser V2](https://github.com/microsoft/omniparser).

## المعمارية الهجينة ثلاثية الطبقات (The 3-Layer Execution Engine)

يختار محرك `munjiz-os-controller` طبقة التنفيذ المثلى تلقائياً بناءً على سياق المهمة لتوفير أقصى سرعة وأقل استهلاك لتوكنز الصور:

| الطبقة (حسب الأولوية) | متى يختارها "مُنجز" تلقائياً؟ | الأداة التقنية في الخلفية | السرعة والدقة واستهلاك التوكنز | 
| ----- | ----- | ----- | ----- | 
| **1. التحكم المباشر بالنظام (System / CLI Layer)** | قراءة ملفات Excel وCSV، إدارة المجلدات، تشغيل البرامج، استعلامات النظام وأوامر Git. | `PowerShell` + `Python Subprocess` + `pandas` | فورية (أجزاء من الثانية) — دقة 100% دون استهلاك توكنز صور. | 
| **2. التحكم الهيكلي بالواجهات والويب (Structural UI & DOM)** | التفاعل مع برامج Windows القياسية (Office, Explorer, Settings) أو أتمتة المتصفح والويب. | `uiautomation` / `pywinauto` (لويندوز) + `browser-use` / `Playwright` (للويب) | سريعة جداً — يقرأ الأزرار والحقول كبيانات JSON وينقر عليها برمجياً عبر `InvokePattern` و`ValuePattern`. | 
| **3. التحكم البصري الخالص وتتبع الماوس (Pure Vision & Live Cursor)** | الأنظمة المحاسبية القديمة، لوحات التصميم، عناصر Canvas، أو عند عدم ظهور العناصر في شجرة UIA. | [OmniParser V2](https://huggingface.co/microsoft/OmniParser-v2.0) (أو كاشف OpenCV الاحتياطي) + `PyAutoGUI` + `pyperclip` | تمنح الوكيل عيناً بصرية ترسم صناديق مرقمة (`Set-of-Mark`) مع تتبع حي لمؤشر الماوس وحلقة نقر مرئية. | 

## أبرز المزايا الهندسية في الإصدار 2.0

* **المشاهدة المرئية الحية وتتبع مؤشر الماوس (`capture_live_view`)**: يعالج مشكلة اختفاء أيقونة الفأرة في لقطات الشاشة القياسية عبر قراءة موقع المؤشر الحقيقي (`user32.GetCursorPos`) ورسم مؤشر واضح (`Crosshair + Halo`) مع خط مسار الحركة (`Trajectory`) من موقع الماوس الحالي إلى العنصر المستهدف.

* **الوميض البصري المباشر على شاشة المستخدم (`show_live_click_ripple`)**: يعرض حلقة ضوئية شفافة عابرة للنقرات (`Click-Through HUD`) فوق شاشة Windows في موضع نقر الوكيل ليشاهد المستخدم بالعين المجردة أين يتفاعل "مُنجز" لحظياً.

* **دعم أصلي وكامل للغة العربية (`keyboard_input`)**: يتجاوز قصور دالة `pyautogui.write()` مع الحروف العربية عبر نسخ النص العربي برمجياً إلى الحافظة (`pyperclip`) وإرسال اختصار اللصق `Ctrl+V`، مع حفظ واستعادة محتوى حافظة المستخدم السابق تلقائياً.

* **معالجة انحراف أبعاد الشاشة (`Per-Monitor DPI Awareness V2`)**: يضبط وعي العملية بدقة الشاشة الحقيقية فور التشغيل لمنع أي انحراف في إحداثيات النقر `(X, Y)` على الشاشات ذات التكبير 125% أو 150% أو 4K.

* **التصعيد التلقائي الذكي (`smart_interact`)**: يحاول التفاعل مع العنصر بالاسم عبر الطبقة الثانية (`Windows UI Automation`) أولاً، وإذا كانت الواجهة مغلقة برمجياً ينتقل تلقائياً إلى الطبقة الثالثة لتحليل الشاشة بصرياً والنقر عبر رقم الصندوق `box_id`.

## هيكل ملفات المستودع

```
munjiz-os-controller/
├── munjiz_os_controller.py   # المحرك الهجين الكامل وخادم FastMCP
├── pyproject.toml            # إعدادات الحزمة والاعتماديات ونقاط التشغيل
└── README.md                 # التوثيق المعماري ودليل الربط مع مُنجز

```

## التثبيت والتجهيز السريع

### 1. تثبيت الحزمة الأساسية

```
git clone https://github.com/<your-org>/munjiz-os-controller.git
cd munjiz-os-controller
pip install -e .

```

لتثبيت دعم أتمتة المتصفح والويب الاختياري عبر `browser-use` و`Playwright`:

```
pip install -e ".[web]"
playwright install chromium

```

### 2. تشغيل الاختبار التشخيصي الذاتي (Self-Test Demo)

يمكنك التحقق من عمل الطبقات الثلاث وتوليد لقطات الشاشة المرقمة وتتبع المؤشر عبر تشغيل وضع المحاكاة:

```
python munjiz_os_controller.py --mode demo

```

## الربط مع تطبيق "مُنجز" عبر بروتوكول MCP

يعمل المحرك كخادم MCP قياسي عبر قناة `stdio`. لربطه مع وكلاء "مُنجز"، أضف الإعداد التالي إلى ملف تكوين جسور الأدوات (`mcp_config.json`):

```
{
  "mcpServers": {
    "munjiz-os-controller": {
      "command": "python",
      "args": [
        "C:/path/to/munjiz-os-controller/munjiz_os_controller.py",
        "--mode",
        "mcp"
      ],
      "env": {
        "MUNJIZ_OMNIPARSER_URL": "http://127.0.0.1:8000/parse",
        "MUNJIZ_LLM_MODEL": "gpt-4o"
      }
    }
  }
}

```

كما يمكنك تشغيله مباشرة بعد تثبيت الحزمة عبر أمر النظام المختصر `munjiz-mcp --mode mcp`.

## دليل الأدوات المتاحة لوكلاء "مُنجز" (MCP Tools Reference)

| اسم الأداة | الطبقة المعمارية | الوظيفة التقنية ومتى يستخدمها الوكيل | 
| ----- | ----- | ----- | 
| `system_cli` | الطبقة 1 (CLI) | تنفيذ أوامر `PowerShell` بترميز `UTF-8` لإدارة الملفات والعمليات بسرعة فائقة مع حماية ضد الأوامر الخطرة. | 
| `read_excel_or_csv` | الطبقة 1 (CLI) | قراءة ملفات الإكسل (`xlsx`) و`CSV` مباشرة في الذاكرة عبر `pandas` دون فتح واجهة برنامج Excel. | 
| `window_manager` | الطبقة 2 (UIA) | عرض قائمة النوافذ المفتوحة (`list`)، تفعيل نافذة في المقدمة (`focus`)، تكبير (`maximize`)، تصغير (`minimize`)، أو إغلاق (`close`). | 
| `inspect_screen` | الطبقة 2 و 3 (Auto) | يفحص النافذة النشطة عبر `uiautomation` أولاً (`mode="auto"`)، وإذا لم تكشف عناصرها برمجياً يحولها تلقائياً إلى [Microsoft OmniParser V2](https://github.com/microsoft/omniparser) لإرجاع عناصر مرقمة (`box_id`) وصورة `Set-of-Mark` مع موقع مؤشر الماوس. | 
| `capture_live_view` | الطبقة 3 (Live Stream) | يلتقط صورة فورية للشاشة مرسوماً عليها مؤشر الماوس الحالي ومسار الحركة لعرضها داخل شاشة المشاهدة الحية في واجهة "مُنجز". | 
| `smart_interact` | موجه هجين (2 ← 3) | يتفاعل مع العنصر عبر اسمه (`target_label`) أو رقم صندوقه (`box_id`)، مع تصعيد تلقائي من الطبقة الهيكلية إلى النقر البصري والكتابة العربية. | 
| `gui_action` | الطبقة 3 (Vision) | يحرك مؤشر الفأرة وينفذ (`click`, `double_click`, `right_click`, `move`, `drag`, `scroll`) مع إظهار حلقة النقر المضيئة (`Live HUD`). | 
| `keyboard_input` | الطبقة 3 (Vision) | يكتب النصوص العربية والإنجليزية بأمان عبر الحافظة (`pyperclip` + `Ctrl+V`) وينفذ اختصارات لوحة المفاتيح (`ctrl+s`, `alt+tab`). | 
| `browser_task` | الطبقة 2 (Web DOM) | يسند مهام التصفح واستخراج بيانات الويب إلى وكيل `browser-use` المبني على `Playwright`. | 

## الاستخدام البرمجي المباشر داخل نواة Python في "مُنجز"

بالإضافة إلى تشغيله كخادم MCP، يمكنك استيراد `MunjizHybridRouter` ومخطط أدوات `get_openai_tools_schema()` مباشرة داخل كود Python الخاص بنواة "مُنجز" وربطه مع نماذج Azure AI Foundry:

```
from munjiz_os_controller import (
    MUNJIZ_ACI_SYSTEM_PROMPT,
    MunjizHybridRouter,
    get_openai_tools_schema,
)

router = MunjizHybridRouter(omniparser_endpoint="http://127.0.0.1:8000/parse")

# 1. قراءة سريعة لملف إكسل عبر الطبقة الأولى (بدون فتح Excel بالماوس)
clients = router.cli_layer.read_tabular_file_fast("C:/Projects/clients.xlsx")

# 2. تفعيل نافذة النظام المحاسبي عبر الطبقة الثانية
router.uia_layer.window_manager(operation="focus", title_query="النظام المحاسبي")

# 3. فحص الشاشة التكيفي والتفاعل الذكي (طبقة 2 ثم تصعيد تلقائي للطبقة 3)
screen_state = router.inspect_screen(mode="auto")
router.smart_interact(
    target_label="اسم العميل",
    action="click",
    text_to_type="شركة آفاق التقنية المتقدمة",
    press_enter=True,
)

```

## الرخصة

مرخص بموجب رخصة MIT.