"""
i18n module for web-config-ui onboarding wizard.

Provides translations for all 11 Demiurgos-supported languages, plus
Jinja2 template integration helpers.  Used by wizard routes and screen
templates to render UI in the user's selected language.

Tone constraints:
  - es (neutro): formal usted, verbos sin voseo ("Seleccione", "Configure")
  - es-ar (rioplatense): voseo natural ("Seleccioná", "Configurá")
  - All languages: warm but professional, never generic/cheerful
  - Never expose internal jargon to the user
"""

from __future__ import annotations

from typing import Callable

# ---------------------------------------------------------------------------
# Language metadata
# ---------------------------------------------------------------------------

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "zh": "中文",
    "hi": "हिन्दी",
    "es": "Español (neutro)",
    "es-ar": "Español (Argentina)",
    "fr": "Français",
    "ar": "العربية",
    "bn": "বাংলা",
    "pt": "Português",
    "ru": "Русский",
    "ur": "اردو",
}

# Default fallback when a requested language or key is missing
_FALLBACK_LANG = "en"

# ---------------------------------------------------------------------------
# Translation tables — 11 languages × ~49 keys
# ---------------------------------------------------------------------------

_LANGUAGES: dict[str, dict[str, str]] = {
    # ==================================================================
    # English
    # ==================================================================
    "en": {
        # -- Screen 0: Language ----------------------------------------
        "welcome_title": "Welcome to Demiurgos",
        "welcome_subtitle": "Your narrative engine for Hermes. Let's set things up.",
        "select_language": "Choose your language",
        "continue_button": "Continue",
        "other": "Other",

        # -- Screen 1: World -------------------------------------------
        "world_title": "Your World",
        "world_subtitle": "Every saga needs a home. Create a new world or load an existing one.",
        "create_new_world": "Create New World",
        "load_existing_world": "Load Existing World",
        "world_name_label": "World name",
        "world_name_placeholder": "e.g., Thalassia, The Forgotten Depths...",
        "select_folder": "Select folder",
        "supported_formats": "Supported formats",
        "format_docx": ".docx (Word) — fully supported",
        "format_md": ".md (Obsidian) — coming soon",
        "format_notion": "Notion export — coming soon",
        "format_pdf": "PDF — coming soon",

        # -- Screen 2: AI ----------------------------------------------
        "ai_title": "Configure AI",
        "ai_subtitle": "Connect Demiurgos to your LLM providers. Text model is required; vision is optional.",
        "provider_label": "Provider",
        "endpoint_label": "Endpoint URL",
        "api_key_label": "API Key",
        "model_text_label": "Text Model",
        "model_vision_label": "Vision Model",
        "test_connection": "Test Connection",
        "testing": "Testing connection…",
        "connection_success": "Connection successful — {count} models found",
        "connection_error": "Connection failed",
        "same_as_text": "Same as text model",
        "vision_warning": "{model} does not support vision. Choose a model marked with 👁️ for vision tasks.",
        "save_config": "Save Configuration",
        "select_model": "Select a model…",
        "select_provider": "Select a provider…",
        "discover_models": "Discover models",

        # -- Screen 3: Images ------------------------------------------
        "images_title": "Image Generation",
        "images_subtitle": "Optional — configure an image generation provider for visual storytelling.",
        "skip_for_now": "Skip for now",
        "configure_later": "Configure later",

        # -- Screen 4: Chats -------------------------------------------
        "chats_title": "Chat Platforms",
        "chats_subtitle": "Optional — connect Demiurgos to Telegram or Discord for mobile access.",

        # -- Screen 5: Backup ------------------------------------------
        "backup_title": "Backup & Sync",
        "backup_subtitle": "Optional — set up automated backups of your worlds and lore.",

        # -- Screen 6: Summary -----------------------------------------
        "summary_title": "Ready to Begin",
        "summary_subtitle": "Here is a summary of your configuration. You can change anything later.",
        "start_using": "Start Using Demiurgos",
        "go_back": "Go Back",
        "world_created": "World created",
        "ai_configured": "AI configured",
        "configured": "Configured",
        "skipped": "Skipped",
        "edit": "Edit",

        # -- Navigation ------------------------------------------------
        "next": "Next",
        "back": "Back",
        "step_x_of_y": "Step {current} of {total}",

        # -- Errors ----------------------------------------------------
        "error_generic": "Something went wrong. Please try again.",
        "error_required_field": "This field is required.",
        "error_connection": "Could not connect to the server. Check your network and try again.",
        "error_timeout": "Connection timed out after {seconds}s",
        "error_connect": "Cannot reach endpoint — check the URL",
        "error_network": "Network error",
        "error_auth_401": "Invalid API key — check your credentials",
        "error_auth_403": "Access denied — check API key permissions",
        "error_endpoint_404": "Endpoint /models not found — is the URL correct?",
        "error_server": "Server error (HTTP {code})",
        "error_json_parse": "Could not read the server response",
        "error_unexpected_format": "Unexpected response format",
        "error_no_models": "No compatible text/image models found",

        # -- Model tags ------------------------------------------------
        "vision_tag_confirmed": "👁️ vision",
        "vision_tag_text_only": "✍️ text",
        "vision_tag_unknown": "❓ unknown",

        # -- Screen 1 extensions ----------------------------------------
        "world_name_hint": "Use lowercase letters, numbers, and hyphens. e.g., mi-mundo",
        "browse_button": "Browse...",

        # -- Screen 2 extensions ----------------------------------------
        "test_vision_connection": "Test Vision Connection",

        # -- Screen 3 extensions ----------------------------------------
        "images_explanation": "Demiurgos can create illustrations of your characters and scenes to bring your world to life.",
        "save_and_continue": "Save and Continue",

        # -- Screen 4 extensions ----------------------------------------
        "chats_explanation": "Connect Demiurgos to your messaging apps so you can write and manage your world from your phone.",
        "telegram": "Telegram",
        "discord": "Discord",
        "coming_soon": "Coming soon",

        # -- Screen 5 extensions ----------------------------------------
        "backup_explanation": "Automatically save your world and lore to Google Drive so you never lose your work.",
        "enable_backup": "Enable automatic backup",
        "rclone_warning": "rclone is required for Google Drive backup. Please install it and run 'rclone config' first.",

        # -- Screen 6 extensions ----------------------------------------
        "language_label": "Language",
        "world_label": "World",
        "ai_text_label": "AI Text",
        "ai_vision_label": "AI Vision",
        "images_label": "Image Generation",
        "chats_label": "Chats",
        "backup_label": "Backup",

        # -- Connection/error fragments ---------------------------------
        "connection_success_title": "Connection successful",
        "connection_success_detail": "Discovered {count} compatible models.",
        "vision_connection_success_detail": "Discovered {count} vision models.",
        "model_select_placeholder": "— Select a model —",
        "model_custom_option": "Other (type manually)",
        "vision_supported_notice": "Provider supports vision. {count} models loaded.",
        "vision_not_supported_notice": "This provider does not support vision. Vision section disabled.",
        "error_title": "Error",
        "error_dismiss_label": "Close",
        "error_connection_hint": "Check the endpoint, API key, and internet connection.",
        "error_test_first": "— Test the connection first —",

        # -- Backup screen extensions ------------------------------------
        "backup_interval_label": "Interval",
        "backup_interval_hourly": "Every hour",
        "backup_interval_daily": "Every day",
        "backup_interval_weekly": "Every week",

        # -- Chat screen extensions --------------------------------------
        "bot_token_label": "Bot Token",
        "enable_chat_platform": "Enable",

        # -- Dashboard / already-configured ------------------------------
        "already_configured_title": "Demiurgos is already configured",
        "already_configured_subtitle": "Your LLM provider is set up. Continue to your world or reconfigure.",
        "continue_to_demiurgos": "Continue to Demiurgos",
        "reconfigure": "Reconfigure",
        "config_dashboard_title": "Configuration",
        "config_dashboard_subtitle": "Manage your Demiurgos settings",
        "not_configured": "Not configured",
        "config_skipped": "Skipped",
        "config_coming_soon": "Full configuration panel coming soon",
        "config_language": "Language",
        "config_world": "World",
        "config_ai": "AI Text & Vision",
        "config_images": "Images",
        "config_chats": "Chats",
        "config_backup": "Backup",
        "restart_wizard": "Restart Wizard",
    },

    # ==================================================================
    # Chinese (Simplified)
    # ==================================================================
    "zh": {
        "welcome_title": "欢迎使用 Demiurgos",
        "welcome_subtitle": "您的 Hermes 叙事引擎。让我们开始配置。",
        "select_language": "选择您的语言",
        "continue_button": "继续",
        "other": "其他",

        "world_title": "您的世界",
        "world_subtitle": "每个传奇都需要一个家园。创建新世界或加载已有世界。",
        "create_new_world": "创建新世界",
        "load_existing_world": "加载已有世界",
        "world_name_label": "世界名称",
        "world_name_placeholder": "例如：深海之境、遗忘深渊…",
        "select_folder": "选择文件夹",
        "supported_formats": "支持的格式",
        "format_docx": ".docx (Word) — 完全支持",
        "format_md": ".md (Obsidian) — 即将推出",
        "format_notion": "Notion 导出 — 即将推出",
        "format_pdf": "PDF — 即将推出",

        "ai_title": "配置 AI",
        "ai_subtitle": "将 Demiurgos 连接到您的 LLM 提供商。文本模型为必选，视觉模型为可选。",
        "provider_label": "提供商",
        "endpoint_label": "端点 URL",
        "api_key_label": "API 密钥",
        "model_text_label": "文本模型",
        "model_vision_label": "视觉模型",
        "test_connection": "测试连接",
        "testing": "正在测试连接…",
        "connection_success": "连接成功 — 找到 {count} 个模型",
        "connection_error": "连接失败",
        "same_as_text": "与文本模型相同",
        "vision_warning": "{model} 不支持视觉。请选择标有 👁️ 的模型用于视觉任务。",
        "save_config": "保存配置",
        "select_model": "选择模型…",
        "select_provider": "选择提供商…",
        "discover_models": "发现模型",

        "images_title": "图像生成",
        "images_subtitle": "可选 — 配置图像生成提供商用于视觉叙事。",
        "skip_for_now": "暂时跳过",
        "configure_later": "稍后配置",

        "chats_title": "聊天平台",
        "chats_subtitle": "可选 — 将 Demiurgos 连接到 Telegram 或 Discord 以实现移动访问。",

        "backup_title": "备份与同步",
        "backup_subtitle": "可选 — 为您的世界和背景设定设置自动备份。",

        "summary_title": "准备开始",
        "summary_subtitle": "以下是您的配置摘要。您可以随时更改。",
        "start_using": "开始使用 Demiurgos",
        "go_back": "返回",
        "world_created": "世界已创建",
        "ai_configured": "AI 已配置",
        "configured": "已配置",
        "skipped": "已跳过",
        "edit": "编辑",

        "next": "下一步",
        "back": "上一步",
        "step_x_of_y": "第 {current} 步，共 {total} 步",

        "error_generic": "出了点问题。请重试。",
        "error_required_field": "此字段为必填项。",
        "error_connection": "无法连接到服务器。请检查网络后重试。",
        "error_timeout": "连接在 {seconds} 秒后超时",
        "error_connect": "无法到达端点 — 请检查 URL",
        "error_network": "网络错误",
        "error_auth_401": "API 密钥无效 — 请检查您的凭据",
        "error_auth_403": "访问被拒绝 — 请检查 API 密钥权限",
        "error_endpoint_404": "未找到 /models 端点 — URL 是否正确？",
        "error_server": "服务器错误 (HTTP {code})",
        "error_json_parse": "无法读取服务器响应",
        "error_unexpected_format": "意外的响应格式",
        "error_no_models": "未找到兼容的文本/图像模型",

        "vision_tag_confirmed": "👁️ 视觉",
        "vision_tag_text_only": "✍️ 文本",
        "vision_tag_unknown": "❓ 未知",

        "world_name_hint": "使用小写字母、数字和连字符。例如：mi-mundo",
        "browse_button": "浏览...",
        "test_vision_connection": "测试视觉连接",
        "images_explanation": "Demiurgos 可以为您的角色和场景创作插画，让您的世界栩栩如生。",
        "save_and_continue": "保存并继续",
        "chats_explanation": "将 Demiurgos 连接到您的通讯应用，以便从手机写作和管理您的世界。",
        "telegram": "Telegram",
        "discord": "Discord",
        "coming_soon": "即将推出",
        "backup_explanation": "自动将您的世界和背景设定保存到 Google Drive，永不错失。",
        "enable_backup": "启用自动备份",
        "rclone_warning": "Google Drive 备份需要 rclone。请先安装并运行 'rclone config'。",
        "language_label": "语言",
        "world_label": "世界",
        "ai_text_label": "AI 文本",
        "ai_vision_label": "AI 视觉",
        "images_label": "图像生成",
        "chats_label": "聊天",
        "backup_label": "备份",

        # -- Connection/error fragments ---------------------------------
        "connection_success_title": "连接成功",
        "connection_success_detail": "发现 {count} 个兼容模型。",
        "vision_connection_success_detail": "发现 {count} 个视觉模型。",
        "model_select_placeholder": "— 选择模型 —",
        "model_custom_option": "其他（手动输入）",
        "vision_supported_notice": "提供商支持视觉。已加载 {count} 个模型。",
        "vision_not_supported_notice": "此提供商不支持视觉。视觉部分已禁用。",
        "error_title": "错误",
        "error_dismiss_label": "关闭",
        "error_connection_hint": "检查端点、API 密钥和互联网连接。",
        "error_test_first": "— 请先测试连接 —",

        # -- Backup screen extensions ------------------------------------
        "backup_interval_label": "间隔",
        "backup_interval_hourly": "每小时",
        "backup_interval_daily": "每天",
        "backup_interval_weekly": "每周",

        # -- Chat screen extensions --------------------------------------
        "bot_token_label": "Bot Token",
        "enable_chat_platform": "启用",

        # -- Dashboard / already-configured ------------------------------
        "already_configured_title": "Demiurgos 已配置",
        "already_configured_subtitle": "您的 LLM 提供商已设置。继续到您的世界或重新配置。",
        "continue_to_demiurgos": "继续使用 Demiurgos",
        "reconfigure": "重新配置",
        "config_dashboard_title": "配置",
        "config_dashboard_subtitle": "管理您的 Demiurgos 设置",
        "not_configured": "未配置",
        "config_skipped": "已跳过",
        "config_coming_soon": "完整配置面板即将推出",
        "config_language": "语言",
        "config_world": "世界",
        "config_ai": "AI 文本与视觉",
        "config_images": "图像",
        "config_chats": "聊天",
        "config_backup": "备份",
        "restart_wizard": "重启向导",
    },

    # ==================================================================
    # Hindi
    # ==================================================================
    "hi": {
        "welcome_title": "Demiurgos में आपका स्वागत है",
        "welcome_subtitle": "Hermes के लिए आपका कथा इंजन। आइए सेटअप करें।",
        "select_language": "अपनी भाषा चुनें",
        "continue_button": "जारी रखें",
        "other": "अन्य",

        "world_title": "आपकी दुनिया",
        "world_subtitle": "हर गाथा को एक घर चाहिए। नई दुनिया बनाएँ या मौजूदा लोड करें।",
        "create_new_world": "नई दुनिया बनाएँ",
        "load_existing_world": "मौजूदा दुनिया लोड करें",
        "world_name_label": "दुनिया का नाम",
        "world_name_placeholder": "जैसे, थैलेसिया, भूली हुई गहराइयाँ…",
        "select_folder": "फ़ोल्डर चुनें",
        "supported_formats": "समर्थित प्रारूप",
        "format_docx": ".docx (Word) — पूरी तरह समर्थित",
        "format_md": ".md (Obsidian) — जल्द आ रहा है",
        "format_notion": "Notion निर्यात — जल्द आ रहा है",
        "format_pdf": "PDF — जल्द आ रहा है",

        "ai_title": "AI कॉन्फ़िगर करें",
        "ai_subtitle": "Demiurgos को अपने LLM प्रदाताओं से जोड़ें। टेक्स्ट मॉडल आवश्यक है; विज़न वैकल्पिक है।",
        "provider_label": "प्रदाता",
        "endpoint_label": "एंडपॉइंट URL",
        "api_key_label": "API कुंजी",
        "model_text_label": "टेक्स्ट मॉडल",
        "model_vision_label": "विज़न मॉडल",
        "test_connection": "कनेक्शन जाँचें",
        "testing": "कनेक्शन जाँच रहे हैं…",
        "connection_success": "कनेक्शन सफल — {count} मॉडल मिले",
        "connection_error": "कनेक्शन विफल",
        "same_as_text": "टेक्स्ट मॉडल के समान",
        "vision_warning": "{model} विज़न का समर्थन नहीं करता। विज़न कार्यों के लिए 👁️ चिह्नित मॉडल चुनें।",
        "save_config": "कॉन्फ़िगरेशन सहेजें",
        "select_model": "मॉडल चुनें…",
        "select_provider": "प्रदाता चुनें…",
        "discover_models": "मॉडल खोजें",

        "images_title": "छवि निर्माण",
        "images_subtitle": "वैकल्पिक — दृश्य कहानी के लिए छवि निर्माण प्रदाता कॉन्फ़िगर करें।",
        "skip_for_now": "अभी छोड़ें",
        "configure_later": "बाद में कॉन्फ़िगर करें",

        "chats_title": "चैट प्लेटफ़ॉर्म",
        "chats_subtitle": "वैकल्पिक — मोबाइल एक्सेस के लिए Demiurgos को Telegram या Discord से जोड़ें।",

        "backup_title": "बैकअप और सिंक",
        "backup_subtitle": "वैकल्पिक — अपनी दुनियाओं और लोर का स्वचालित बैकअप सेट करें।",

        "summary_title": "शुरू करने के लिए तैयार",
        "summary_subtitle": "यहाँ आपके कॉन्फ़िगरेशन का सारांश है। आप बाद में कुछ भी बदल सकते हैं।",
        "start_using": "Demiurgos का उपयोग शुरू करें",
        "go_back": "वापस जाएँ",
        "world_created": "दुनिया बनाई गई",
        "ai_configured": "AI कॉन्फ़िगर किया गया",
        "configured": "कॉन्फ़िगर किया गया",
        "skipped": "छोड़ा गया",
        "edit": "संपादित करें",

        "next": "अगला",
        "back": "पिछला",
        "step_x_of_y": "चरण {current} / {total}",

        "error_generic": "कुछ गलत हो गया। कृपया पुनः प्रयास करें।",
        "error_required_field": "यह फ़ील्ड आवश्यक है।",
        "error_connection": "सर्वर से कनेक्ट नहीं हो सका। अपना नेटवर्क जाँचें और पुनः प्रयास करें।",
        "error_timeout": "{seconds} सेकंड के बाद कनेक्शन का समय समाप्त",
        "error_connect": "एंडपॉइंट तक नहीं पहुंच सकते — URL जांचें",
        "error_network": "नेटवर्क त्रुटि",
        "error_auth_401": "अमान्य API कुंजी — अपने क्रेडेंशियल जांचें",
        "error_auth_403": "पहुंच अस्वीकृत — API कुंजी अनुमतियां जांचें",
        "error_endpoint_404": "/models एंडपॉइंट नहीं मिला — क्या URL सही है?",
        "error_server": "सर्वर त्रुटि (HTTP {code})",
        "error_json_parse": "सर्वर प्रतिक्रिया पढ़ नहीं सके",
        "error_unexpected_format": "अप्रत्याशित प्रतिक्रिया प्रारूप",
        "error_no_models": "कोई संगत टेक्स्ट/इमेज मॉडल नहीं मिला",

        "vision_tag_confirmed": "👁️ विज़न",
        "vision_tag_text_only": "✍️ टेक्स्ट",
        "vision_tag_unknown": "❓ अज्ञात",

        "world_name_hint": "छोटे अक्षरों, संख्याओं और हाइफ़न का उपयोग करें। जैसे, mi-mundo",
        "browse_button": "ब्राउज़ करें...",
        "test_vision_connection": "विज़न कनेक्शन जाँचें",
        "images_explanation": "Demiurgos आपके पात्रों और दृश्यों के चित्र बना सकता है।",
        "save_and_continue": "सहेजें और जारी रखें",
        "chats_explanation": "अपने फ़ोन से लिखने और दुनिया प्रबंधित करने के लिए Demiurgos को मैसेजिंग ऐप से जोड़ें।",
        "telegram": "Telegram",
        "discord": "Discord",
        "coming_soon": "जल्द आ रहा है",
        "backup_explanation": "अपनी दुनिया और लोर को Google Drive पर स्वचालित रूप से सहेजें।",
        "enable_backup": "स्वचालित बैकअप सक्षम करें",
        "rclone_warning": "Google Drive बैकअप के लिए rclone आवश्यक है। कृपया इसे इंस्टॉल करें और 'rclone config' चलाएँ।",
        "language_label": "भाषा",
        "world_label": "दुनिया",
        "ai_text_label": "AI टेक्स्ट",
        "ai_vision_label": "AI विज़न",
        "images_label": "छवि निर्माण",
        "chats_label": "चैट",
        "backup_label": "बैकअप",

        # -- Connection/error fragments ---------------------------------
        "connection_success_title": "कनेक्शन सफल",
        "connection_success_detail": "{count} संगत मॉडल मिले।",
        "vision_connection_success_detail": "{count} विज़न मॉडल मिले।",
        "model_select_placeholder": "— मॉडल चुनें —",
        "model_custom_option": "अन्य (मैन्युअल टाइप करें)",
        "vision_supported_notice": "प्रदाता विज़न समर्थित करता है। {count} मॉडल लोड हुए।",
        "vision_not_supported_notice": "यह प्रदाता विज़न समर्थित नहीं करता। विज़न अनुभाग अक्षम।",
        "error_title": "त्रुटि",
        "error_dismiss_label": "बंद करें",
        "error_connection_hint": "एंडपॉइंट, API की और इंटरनेट कनेक्शन जाँचें।",
        "error_test_first": "— पहले कनेक्शन जाँचें —",

        # -- Backup screen extensions ------------------------------------
        "backup_interval_label": "अंतराल",
        "backup_interval_hourly": "हर घंटे",
        "backup_interval_daily": "हर दिन",
        "backup_interval_weekly": "हर सप्ताह",

        # -- Chat screen extensions --------------------------------------
        "bot_token_label": "Bot Token",
        "enable_chat_platform": "सक्षम करें",

        # -- Dashboard / already-configured ------------------------------
        "already_configured_title": "Demiurgos पहले से कॉन्फ़िगर है",
        "already_configured_subtitle": "आपका LLM प्रदाता सेट है। अपनी दुनिया में जाएं या पुनः कॉन्फ़िगर करें।",
        "continue_to_demiurgos": "Demiurgos पर जारी रखें",
        "reconfigure": "पुनः कॉन्फ़िगर करें",
        "config_dashboard_title": "कॉन्फ़िगरेशन",
        "config_dashboard_subtitle": "अपनी Demiurgos सेटिंग प्रबंधित करें",
        "not_configured": "कॉन्फ़िगर नहीं किया गया",
        "config_skipped": "छोड़ा गया",
        "config_coming_soon": "पूर्ण कॉन्फ़िगरेशन पैनल जल्द आ रहा है",
        "config_language": "भाषा",
        "config_world": "दुनिया",
        "config_ai": "AI टेक्स्ट और विज़न",
        "config_images": "छवियां",
        "config_chats": "चैट",
        "config_backup": "बैकअप",
        "restart_wizard": "विज़ार्ड पुनः आरंभ करें",
    },

    # ==================================================================
    # Spanish (neutral — formal usted, no voseo)
    # ==================================================================
    "es": {
        "welcome_title": "Bienvenido a Demiurgos",
        "welcome_subtitle": "Su motor narrativo para Hermes. Configuremos todo.",
        "select_language": "Seleccione su idioma",
        "continue_button": "Continuar",
        "other": "Otro",

        "world_title": "Su Mundo",
        "world_subtitle": "Toda saga necesita un hogar. Cree un nuevo mundo o cargue uno existente.",
        "create_new_world": "Crear Nuevo Mundo",
        "load_existing_world": "Cargar Mundo Existente",
        "world_name_label": "Nombre del mundo",
        "world_name_placeholder": "ej., Thalassia, Las Profundidades Olvidadas…",
        "select_folder": "Seleccionar carpeta",
        "supported_formats": "Formatos soportados",
        "format_docx": ".docx (Word) — totalmente soportado",
        "format_md": ".md (Obsidian) — próximamente",
        "format_notion": "Exportación de Notion — próximamente",
        "format_pdf": "PDF — próximamente",

        "ai_title": "Configurar IA",
        "ai_subtitle": "Conecte Demiurgos a sus proveedores LLM. El modelo de texto es obligatorio; visión es opcional.",
        "provider_label": "Proveedor",
        "endpoint_label": "URL del endpoint",
        "api_key_label": "API Key",
        "model_text_label": "Modelo de texto",
        "model_vision_label": "Modelo de visión",
        "test_connection": "Probar Conexión",
        "testing": "Probando conexión…",
        "connection_success": "Conexión exitosa — {count} modelos encontrados",
        "connection_error": "Error de conexión",
        "same_as_text": "Mismo que modelo de texto",
        "vision_warning": "{model} no soporta visión. Seleccione un modelo marcado con 👁️ para tareas de visión.",
        "save_config": "Guardar Configuración",
        "select_model": "Seleccione un modelo…",
        "select_provider": "Seleccione un proveedor…",
        "discover_models": "Descubrir modelos",

        "images_title": "Generación de Imágenes",
        "images_subtitle": "Opcional — configure un proveedor de imágenes para narración visual.",
        "skip_for_now": "Saltar por ahora",
        "configure_later": "Configurar después",

        "chats_title": "Plataformas de Chat",
        "chats_subtitle": "Opcional — conecte Demiurgos a Telegram o Discord para acceso móvil.",

        "backup_title": "Respaldo y Sincronización",
        "backup_subtitle": "Opcional — configure respaldos automáticos de sus mundos y lore.",

        "summary_title": "Listo para Empezar",
        "summary_subtitle": "Aquí tiene un resumen de su configuración. Puede cambiar todo después.",
        "start_using": "Comenzar a Usar Demiurgos",
        "go_back": "Volver",
        "world_created": "Mundo creado",
        "ai_configured": "IA configurada",
        "configured": "Configurado",
        "skipped": "Omitido",
        "edit": "Editar",

        "next": "Siguiente",
        "back": "Atrás",
        "step_x_of_y": "Paso {current} de {total}",

        "error_generic": "Algo salió mal. Intente de nuevo.",
        "error_required_field": "Este campo es obligatorio.",
        "error_connection": "No se pudo conectar al servidor. Verifique su red e intente de nuevo.",
        "error_timeout": "Timeout tras {seconds}s",
        "error_connect": "Endpoint inalcanzable — verificá la URL",
        "error_network": "Error de red",
        "error_auth_401": "API key inválida — revisá tus credenciales",
        "error_auth_403": "Acceso denegado — revisá los permisos",
        "error_endpoint_404": "Endpoint /models no encontrado — ¿la URL es correcta?",
        "error_server": "Error del servidor (HTTP {code})",
        "error_json_parse": "No se pudo leer la respuesta del servidor",
        "error_unexpected_format": "Formato de respuesta inesperado",
        "error_no_models": "No se encontraron modelos compatibles",

        "vision_tag_confirmed": "👁️ visión",
        "vision_tag_text_only": "✍️ texto",
        "vision_tag_unknown": "❓ desconocido",

        "world_name_hint": "Use minúsculas, números y guiones. Ej.: mi-mundo",
        "browse_button": "Explorar...",
        "test_vision_connection": "Probar Conexión de Visión",
        "images_explanation": "Demiurgos puede crear ilustraciones de sus personajes y escenas para dar vida a su mundo.",
        "save_and_continue": "Guardar y Continuar",
        "chats_explanation": "Conecte Demiurgos a sus aplicaciones de mensajería para escribir y gestionar su mundo desde el teléfono.",
        "telegram": "Telegram",
        "discord": "Discord",
        "coming_soon": "Próximamente",
        "backup_explanation": "Guarde su mundo y lore automáticamente en Google Drive para no perder nunca su trabajo.",
        "enable_backup": "Activar respaldo automático",
        "rclone_warning": "rclone es necesario para el respaldo en Google Drive. Instálelo y ejecute 'rclone config' primero.",
        "language_label": "Idioma",
        "world_label": "Mundo",
        "ai_text_label": "IA de Texto",
        "ai_vision_label": "IA de Visión",
        "images_label": "Generación de Imágenes",
        "chats_label": "Chats",
        "backup_label": "Respaldo",

        # -- Fragmentos de conexión/error --------------------------------
        "connection_success_title": "Conexión exitosa",
        "connection_success_detail": "Se descubrieron {count} modelos compatibles.",
        "vision_connection_success_detail": "Se descubrieron {count} modelos de visión.",
        "model_select_placeholder": "— Seleccione un modelo —",
        "model_custom_option": "Otro (escribir manualmente)",
        "vision_supported_notice": "El proveedor soporta visión. {count} modelos cargados.",
        "vision_not_supported_notice": "Este proveedor no soporta visión. Sección de visión deshabilitada.",
        "error_title": "Error",
        "error_dismiss_label": "Cerrar",
        "error_connection_hint": "Verifique el endpoint, la API key y su conexión a internet.",
        "error_test_first": "— Pruebe la conexión primero —",

        # -- Pantalla de respaldo ----------------------------------------
        "backup_interval_label": "Intervalo",
        "backup_interval_hourly": "Cada hora",
        "backup_interval_daily": "Cada día",
        "backup_interval_weekly": "Cada semana",

        # -- Pantalla de chats -------------------------------------------
        "bot_token_label": "Bot Token",
        "enable_chat_platform": "Activar",

        # -- Dashboard / already-configured ------------------------------
        "already_configured_title": "Demiurgos ya está configurado",
        "already_configured_subtitle": "Su proveedor LLM está listo. Continúe a su mundo o reconfigure.",
        "continue_to_demiurgos": "Continuar a Demiurgos",
        "reconfigure": "Reconfigurar",
        "config_dashboard_title": "Configuración",
        "config_dashboard_subtitle": "Gestione su configuración de Demiurgos",
        "not_configured": "No configurado",
        "config_skipped": "Omitido",
        "config_coming_soon": "Panel de configuración completo próximamente",
        "config_language": "Idioma",
        "config_world": "Mundo",
        "config_ai": "IA Texto y Visión",
        "config_images": "Imágenes",
        "config_chats": "Chats",
        "config_backup": "Respaldo",
        "restart_wizard": "Reiniciar Asistente",
    },

    # ==================================================================
    # Spanish (Rioplatense — voseo natural)
    # ==================================================================
    "es-ar": {
        "welcome_title": "Bienvenido a Demiurgos",
        "welcome_subtitle": "Tu motor narrativo para Hermes. Configuremos todo.",
        "select_language": "Elegí tu idioma",
        "continue_button": "Continuar",
        "other": "Otro",

        "world_title": "Tu Mundo",
        "world_subtitle": "Toda saga necesita un hogar. Creá un nuevo mundo o cargá uno existente.",
        "create_new_world": "Crear Nuevo Mundo",
        "load_existing_world": "Cargar Mundo Existente",
        "world_name_label": "Nombre del mundo",
        "world_name_placeholder": "ej., Thalassia, Las Profundidades Olvidadas…",
        "select_folder": "Seleccionar carpeta",
        "supported_formats": "Formatos soportados",
        "format_docx": ".docx (Word) — totalmente soportado",
        "format_md": ".md (Obsidian) — próximamente",
        "format_notion": "Exportación de Notion — próximamente",
        "format_pdf": "PDF — próximamente",

        "ai_title": "Configurar IA",
        "ai_subtitle": "Conectá Demiurgos a tus proveedores LLM. El modelo de texto es obligatorio; visión es opcional.",
        "provider_label": "Proveedor",
        "endpoint_label": "URL del endpoint",
        "api_key_label": "API Key",
        "model_text_label": "Modelo de texto",
        "model_vision_label": "Modelo de visión",
        "test_connection": "Probar Conexión",
        "testing": "Probando conexión…",
        "connection_success": "Conexión exitosa — {count} modelos encontrados",
        "connection_error": "Error de conexión",
        "same_as_text": "Mismo que modelo de texto",
        "vision_warning": "{model} no soporta visión. Elegí un modelo marcado con 👁️ para tareas de visión.",
        "save_config": "Guardar Configuración",
        "select_model": "Seleccioná un modelo…",
        "select_provider": "Seleccioná un proveedor…",
        "discover_models": "Descubrir modelos",

        "images_title": "Generación de Imágenes",
        "images_subtitle": "Opcional — configurá un proveedor de imágenes para narración visual.",
        "skip_for_now": "Saltar por ahora",
        "configure_later": "Configurar después",

        "chats_title": "Plataformas de Chat",
        "chats_subtitle": "Opcional — conectá Demiurgos a Telegram o Discord para acceso móvil.",

        "backup_title": "Respaldo y Sincronización",
        "backup_subtitle": "Opcional — configurá respaldos automáticos de tus mundos y lore.",

        "summary_title": "Listo para Arrancar",
        "summary_subtitle": "Acá tenés un resumen de tu configuración. Podés cambiar todo después.",
        "start_using": "Comenzar a Usar Demiurgos",
        "go_back": "Volver",
        "world_created": "Mundo creado",
        "ai_configured": "IA configurada",
        "configured": "Configurado",
        "skipped": "Omitido",
        "edit": "Editar",

        "next": "Siguiente",
        "back": "Atrás",
        "step_x_of_y": "Paso {current} de {total}",

        "error_generic": "Algo salió mal. Intentá de nuevo.",
        "error_required_field": "Este campo es obligatorio.",
        "error_connection": "No se pudo conectar al servidor. Verificá tu red e intentá de nuevo.",
        "error_timeout": "Timeout después de {seconds}s",
        "error_connect": "Endpoint inalcanzable — revisá la URL",
        "error_network": "Error de red",
        "error_auth_401": "API key inválida — revisá tus credenciales",
        "error_auth_403": "Acceso denegado — revisá los permisos",
        "error_endpoint_404": "Endpoint /models no encontrado — ¿la URL es correcta?",
        "error_server": "Error del servidor (HTTP {code})",
        "error_json_parse": "No se pudo leer la respuesta del servidor",
        "error_unexpected_format": "Formato de respuesta inesperado",
        "error_no_models": "No se encontraron modelos compatibles",

        "vision_tag_confirmed": "👁️ visión",
        "vision_tag_text_only": "✍️ texto",
        "vision_tag_unknown": "❓ desconocido",

        "world_name_hint": "Usá minúsculas, números y guiones. Ej.: mi-mundo",
        "browse_button": "Explorar...",
        "test_vision_connection": "Probá Conexión de Visión",
        "images_explanation": "Demiurgos puede crear ilustraciones de tus personajes y escenas para darle vida a tu mundo.",
        "save_and_continue": "Guardar y Continuar",
        "chats_explanation": "Conectá Demiurgos a tus apps de mensajería para escribir y gestionar tu mundo desde el celu.",
        "telegram": "Telegram",
        "discord": "Discord",
        "coming_soon": "Próximamente",
        "backup_explanation": "Guardá tu mundo y lore automáticamente en Google Drive para no perder nunca tu trabajo.",
        "enable_backup": "Activar respaldo automático",
        "rclone_warning": "rclone es necesario para el respaldo en Google Drive. Instalalo y ejecutá 'rclone config' primero.",
        "language_label": "Idioma",
        "world_label": "Mundo",
        "ai_text_label": "IA de Texto",
        "ai_vision_label": "IA de Visión",
        "images_label": "Generación de Imágenes",
        "chats_label": "Chats",
        "backup_label": "Respaldo",

        # -- Fragmentos de conexión/error --------------------------------
        "connection_success_title": "Conexión exitosa",
        "connection_success_detail": "Se descubrieron {count} modelos compatibles.",
        "vision_connection_success_detail": "Se descubrieron {count} modelos de visión.",
        "model_select_placeholder": "— Seleccioná un modelo —",
        "model_custom_option": "Otro (escribir manualmente)",
        "vision_supported_notice": "El proveedor soporta visión. {count} modelos cargados.",
        "vision_not_supported_notice": "Este proveedor no soporta visión. Sección de visión deshabilitada.",
        "error_title": "Error",
        "error_dismiss_label": "Cerrar",
        "error_connection_hint": "Verificá el endpoint, la API key y tu conexión a internet.",
        "error_test_first": "— Probá la conexión primero —",

        # -- Pantalla de respaldo ----------------------------------------
        "backup_interval_label": "Intervalo",
        "backup_interval_hourly": "Cada hora",
        "backup_interval_daily": "Cada día",
        "backup_interval_weekly": "Cada semana",

        # -- Pantalla de chats -------------------------------------------
        "bot_token_label": "Bot Token",
        "enable_chat_platform": "Activar",

        # -- Dashboard / already-configured ------------------------------
        "already_configured_title": "Demiurgos ya está configurado",
        "already_configured_subtitle": "Tu proveedor LLM está listo. Continuá a tu mundo o reconfigurá.",
        "continue_to_demiurgos": "Continuar a Demiurgos",
        "reconfigure": "Reconfigurar",
        "config_dashboard_title": "Configuración",
        "config_dashboard_subtitle": "Gestioná tu configuración de Demiurgos",
        "not_configured": "No configurado",
        "config_skipped": "Omitido",
        "config_coming_soon": "Panel de configuración completo próximamente",
        "config_language": "Idioma",
        "config_world": "Mundo",
        "config_ai": "IA Texto y Visión",
        "config_images": "Imágenes",
        "config_chats": "Chats",
        "config_backup": "Respaldo",
        "restart_wizard": "Reiniciar Asistente",
    },

    # ==================================================================
    # French
    # ==================================================================
    "fr": {
        "welcome_title": "Bienvenue sur Demiurgos",
        "welcome_subtitle": "Votre moteur narratif pour Hermes. Configurons tout cela.",
        "select_language": "Choisissez votre langue",
        "continue_button": "Continuer",
        "other": "Autre",

        "world_title": "Votre Monde",
        "world_subtitle": "Toute saga a besoin d'un foyer. Créez un nouveau monde ou chargez-en un existant.",
        "create_new_world": "Créer un Nouveau Monde",
        "load_existing_world": "Charger un Monde Existant",
        "world_name_label": "Nom du monde",
        "world_name_placeholder": "ex., Thalassia, Les Profondeurs Oubliées…",
        "select_folder": "Sélectionner un dossier",
        "supported_formats": "Formats supportés",
        "format_docx": ".docx (Word) — entièrement supporté",
        "format_md": ".md (Obsidian) — bientôt disponible",
        "format_notion": "Export Notion — bientôt disponible",
        "format_pdf": "PDF — bientôt disponible",

        "ai_title": "Configurer l'IA",
        "ai_subtitle": "Connectez Demiurgos à vos fournisseurs LLM. Le modèle texte est requis ; la vision est optionnelle.",
        "provider_label": "Fournisseur",
        "endpoint_label": "URL du endpoint",
        "api_key_label": "Clé API",
        "model_text_label": "Modèle texte",
        "model_vision_label": "Modèle vision",
        "test_connection": "Tester la Connexion",
        "testing": "Test de connexion…",
        "connection_success": "Connexion réussie — {count} modèles trouvés",
        "connection_error": "Échec de connexion",
        "same_as_text": "Identique au modèle texte",
        "vision_warning": "{model} ne supporte pas la vision. Choisissez un modèle marqué 👁️ pour les tâches visuelles.",
        "save_config": "Enregistrer la Configuration",
        "select_model": "Sélectionnez un modèle…",
        "select_provider": "Sélectionnez un fournisseur…",
        "discover_models": "Découvrir les modèles",

        "images_title": "Génération d'Images",
        "images_subtitle": "Optionnel — configurez un fournisseur d'images pour la narration visuelle.",
        "skip_for_now": "Passer pour l'instant",
        "configure_later": "Configurer plus tard",

        "chats_title": "Plateformes de Chat",
        "chats_subtitle": "Optionnel — connectez Demiurgos à Telegram ou Discord pour un accès mobile.",

        "backup_title": "Sauvegarde et Synchro",
        "backup_subtitle": "Optionnel — configurez des sauvegardes automatiques de vos mondes et lore.",

        "summary_title": "Prêt à Démarrer",
        "summary_subtitle": "Voici un résumé de votre configuration. Vous pouvez tout modifier plus tard.",
        "start_using": "Commencer à Utiliser Demiurgos",
        "go_back": "Retour",
        "world_created": "Monde créé",
        "ai_configured": "IA configurée",
        "configured": "Configuré",
        "skipped": "Ignoré",
        "edit": "Modifier",

        "next": "Suivant",
        "back": "Retour",
        "step_x_of_y": "Étape {current} sur {total}",

        "error_generic": "Quelque chose s'est mal passé. Veuillez réessayer.",
        "error_required_field": "Ce champ est obligatoire.",
        "error_connection": "Impossible de se connecter au serveur. Vérifiez votre réseau et réessayez.",
        "error_timeout": "Délai de connexion dépassé après {seconds}s",
        "error_connect": "Endpoint inaccessible — vérifiez l'URL",
        "error_network": "Erreur réseau",
        "error_auth_401": "Clé API invalide — vérifiez vos identifiants",
        "error_auth_403": "Accès refusé — vérifiez les permissions de la clé API",
        "error_endpoint_404": "Endpoint /models introuvable — l'URL est-elle correcte ?",
        "error_server": "Erreur serveur (HTTP {code})",
        "error_json_parse": "Impossible de lire la réponse du serveur",
        "error_unexpected_format": "Format de réponse inattendu",
        "error_no_models": "Aucun modèle texte/image compatible trouvé",

        "vision_tag_confirmed": "👁️ vision",
        "vision_tag_text_only": "✍️ texte",
        "vision_tag_unknown": "❓ inconnu",

        "world_name_hint": "Utilisez des minuscules, chiffres et tirets. Ex. : mi-mundo",
        "browse_button": "Parcourir...",
        "test_vision_connection": "Tester la Connexion Vision",
        "images_explanation": "Demiurgos peut créer des illustrations de vos personnages et scènes pour donner vie à votre monde.",
        "save_and_continue": "Enregistrer et Continuer",
        "chats_explanation": "Connectez Demiurgos à vos applications de messagerie pour écrire et gérer votre monde depuis votre téléphone.",
        "telegram": "Telegram",
        "discord": "Discord",
        "coming_soon": "Bientôt disponible",
        "backup_explanation": "Sauvegardez automatiquement votre monde et lore sur Google Drive pour ne jamais perdre votre travail.",
        "enable_backup": "Activer la sauvegarde automatique",
        "rclone_warning": "rclone est requis pour la sauvegarde Google Drive. Installez-le et exécutez 'rclone config' d'abord.",
        "language_label": "Langue",
        "world_label": "Monde",
        "ai_text_label": "IA Texte",
        "ai_vision_label": "IA Vision",
        "images_label": "Génération d'Images",
        "chats_label": "Chats",
        "backup_label": "Sauvegarde",

        # -- Fragments connexion/erreur ----------------------------------
        "connection_success_title": "Connexion réussie",
        "connection_success_detail": "{count} modèles compatibles découverts.",
        "vision_connection_success_detail": "{count} modèles de vision découverts.",
        "model_select_placeholder": "— Sélectionnez un modèle —",
        "model_custom_option": "Autre (saisir manuellement)",
        "vision_supported_notice": "Le fournisseur prend en charge la vision. {count} modèles chargés.",
        "vision_not_supported_notice": "Ce fournisseur ne prend pas en charge la vision. Section vision désactivée.",
        "error_title": "Erreur",
        "error_dismiss_label": "Fermer",
        "error_connection_hint": "Vérifiez l'endpoint, la clé API et votre connexion internet.",
        "error_test_first": "— Testez la connexion d'abord —",

        # -- Écran sauvegarde --------------------------------------------
        "backup_interval_label": "Intervalle",
        "backup_interval_hourly": "Toutes les heures",
        "backup_interval_daily": "Tous les jours",
        "backup_interval_weekly": "Toutes les semaines",

        # -- Écran chats -------------------------------------------------
        "bot_token_label": "Bot Token",
        "enable_chat_platform": "Activer",

        # -- Dashboard / already-configured ------------------------------
        "already_configured_title": "Demiurgos est déjà configuré",
        "already_configured_subtitle": "Votre fournisseur LLM est configuré. Continuez vers votre monde ou reconfigurez.",
        "continue_to_demiurgos": "Continuer vers Demiurgos",
        "reconfigure": "Reconfigurer",
        "config_dashboard_title": "Configuration",
        "config_dashboard_subtitle": "Gérez vos paramètres Demiurgos",
        "not_configured": "Non configuré",
        "config_skipped": "Ignoré",
        "config_coming_soon": "Panneau de configuration complet bientôt disponible",
        "config_language": "Langue",
        "config_world": "Monde",
        "config_ai": "IA Texte et Vision",
        "config_images": "Images",
        "config_chats": "Chats",
        "config_backup": "Sauvegarde",
        "restart_wizard": "Redémarrer l'assistant",
    },

    # ==================================================================
    # Arabic
    # ==================================================================
    "ar": {
        "welcome_title": "مرحباً بك في Demiurgos",
        "welcome_subtitle": "محركك السردي لـ Hermes. هيا لنُعد الإعدادات.",
        "select_language": "اختر لغتك",
        "continue_button": "متابعة",
        "other": "أخرى",

        "world_title": "عالمك",
        "world_subtitle": "كل ملحمة تحتاج إلى موطن. أنشئ عالماً جديداً أو حمّل عالماً موجوداً.",
        "create_new_world": "إنشاء عالم جديد",
        "load_existing_world": "تحميل عالم موجود",
        "world_name_label": "اسم العالم",
        "world_name_placeholder": "مثال: ثالاسيا، الأعماق المنسية…",
        "select_folder": "اختيار مجلد",
        "supported_formats": "الصيغ المدعومة",
        "format_docx": ".docx (Word) — مدعوم بالكامل",
        "format_md": ".md (Obsidian) — قريباً",
        "format_notion": "تصدير Notion — قريباً",
        "format_pdf": "PDF — قريباً",

        "ai_title": "تكوين الذكاء الاصطناعي",
        "ai_subtitle": "اربط Demiurgos بمزوّدي LLM. نموذج النص مطلوب؛ الرؤية اختيارية.",
        "provider_label": "المزوّد",
        "endpoint_label": "رابط النقطة الطرفية",
        "api_key_label": "مفتاح API",
        "model_text_label": "نموذج النص",
        "model_vision_label": "نموذج الرؤية",
        "test_connection": "اختبار الاتصال",
        "testing": "جارٍ اختبار الاتصال…",
        "connection_success": "تم الاتصال بنجاح — تم العثور على {count} نموذج",
        "connection_error": "فشل الاتصال",
        "same_as_text": "نفس نموذج النص",
        "vision_warning": "{model} لا يدعم الرؤية. اختر نموذجاً موسوماً بـ 👁️ لمهام الرؤية.",
        "save_config": "حفظ التكوين",
        "select_model": "اختر نموذجاً…",
        "select_provider": "اختر مزوّداً…",
        "discover_models": "اكتشاف النماذج",

        "images_title": "توليد الصور",
        "images_subtitle": "اختياري — كوّن مزوّد صور للسرد البصري.",
        "skip_for_now": "تخطَّ الآن",
        "configure_later": "التكوين لاحقاً",

        "chats_title": "منصات الدردشة",
        "chats_subtitle": "اختياري — اربط Demiurgos بـ Telegram أو Discord للوصول عبر الجوال.",

        "backup_title": "النسخ الاحتياطي والمزامنة",
        "backup_subtitle": "اختياري — إعداد نسخ احتياطية تلقائية لعوالمك ومعلوماتك.",

        "summary_title": "جاهز للبدء",
        "summary_subtitle": "إليك ملخص لإعداداتك. يمكنك تغيير أي شيء لاحقاً.",
        "start_using": "ابدأ استخدام Demiurgos",
        "go_back": "رجوع",
        "world_created": "تم إنشاء العالم",
        "ai_configured": "تم تكوين الذكاء الاصطناعي",
        "configured": "مُكوَّن",
        "skipped": "تم التخطي",
        "edit": "تعديل",

        "next": "التالي",
        "back": "السابق",
        "step_x_of_y": "الخطوة {current} من {total}",

        "error_generic": "حدث خطأ ما. يرجى المحاولة مرة أخرى.",
        "error_required_field": "هذا الحقل مطلوب.",
        "error_connection": "تعذر الاتصال بالخادم. تحقق من شبكتك وحاول مرة أخرى.",
        "error_timeout": "انتهت مهلة الاتصال بعد {seconds} ثانية",
        "error_connect": "لا يمكن الوصول إلى النقطة الطرفية — تحقق من الرابط",
        "error_network": "خطأ في الشبكة",
        "error_auth_401": "مفتاح API غير صالح — تحقق من بيانات اعتمادك",
        "error_auth_403": "تم رفض الوصول — تحقق من صلاحيات مفتاح API",
        "error_endpoint_404": "النقطة الطرفية /models غير موجودة — هل الرابط صحيح؟",
        "error_server": "خطأ في الخادم (HTTP {code})",
        "error_json_parse": "تعذرت قراءة استجابة الخادم",
        "error_unexpected_format": "تنسيق استجابة غير متوقع",
        "error_no_models": "لم يتم العثور على نماذج نص/صورة متوافقة",

        "vision_tag_confirmed": "👁️ رؤية",
        "vision_tag_text_only": "✍️ نص",
        "vision_tag_unknown": "❓ غير معروف",

        "world_name_hint": "استخدم أحرفاً صغيرة وأرقاماً وشرطات. مثال: mi-mundo",
        "browse_button": "تصفح...",
        "test_vision_connection": "اختبار اتصال الرؤية",
        "images_explanation": "يمكن لـ Demiurgos إنشاء رسوم توضيحية لشخصياتك ومشاهدك لإضفاء الحياة على عالمك.",
        "save_and_continue": "حفظ ومتابعة",
        "chats_explanation": "اربط Demiurgos بتطبيقات المراسلة للكتابة وإدارة عالمك من هاتفك.",
        "telegram": "Telegram",
        "discord": "Discord",
        "coming_soon": "قريباً",
        "backup_explanation": "احفظ عالمك ومعلوماتك تلقائياً على Google Drive لكي لا تفقد عملك أبداً.",
        "enable_backup": "تفعيل النسخ الاحتياطي التلقائي",
        "rclone_warning": "rclone مطلوب للنسخ الاحتياطي على Google Drive. ثبّته وشغّل 'rclone config' أولاً.",
        "language_label": "اللغة",
        "world_label": "العالم",
        "ai_text_label": "الذكاء الاصطناعي للنص",
        "ai_vision_label": "الذكاء الاصطناعي للرؤية",
        "images_label": "توليد الصور",
        "chats_label": "الدردشات",
        "backup_label": "النسخ الاحتياطي",

        # -- أجزاء الاتصال/الخطأ -----------------------------------------
        "connection_success_title": "تم الاتصال بنجاح",
        "connection_success_detail": "تم اكتشاف {count} نموذج متوافق.",
        "vision_connection_success_detail": "تم اكتشاف {count} نموذج رؤية.",
        "model_select_placeholder": "— اختر نموذجاً —",
        "model_custom_option": "آخر (اكتب يدوياً)",
        "vision_supported_notice": "المزود يدعم الرؤية. تم تحميل {count} نموذج.",
        "vision_not_supported_notice": "هذا المزود لا يدعم الرؤية. قسم الرؤية معطل.",
        "error_title": "خطأ",
        "error_dismiss_label": "إغلاق",
        "error_connection_hint": "تحقق من النقطة الطرفية ومفتاح API واتصالك بالإنترنت.",
        "error_test_first": "— اختبر الاتصال أولاً —",

        # -- شاشة النسخ الاحتياطي ----------------------------------------
        "backup_interval_label": "الفاصل",
        "backup_interval_hourly": "كل ساعة",
        "backup_interval_daily": "كل يوم",
        "backup_interval_weekly": "كل أسبوع",

        # -- شاشة الدردشة -------------------------------------------------
        "bot_token_label": "Bot Token",
        "enable_chat_platform": "تفعيل",

        # -- Dashboard / already-configured ------------------------------
        "already_configured_title": "Demiurgos مُهيأ بالفعل",
        "already_configured_subtitle": "تم إعداد مزود LLM الخاص بك. تابع إلى عالمك أو أعد التهيئة.",
        "continue_to_demiurgos": "المتابعة إلى Demiurgos",
        "reconfigure": "إعادة التهيئة",
        "config_dashboard_title": "التهيئة",
        "config_dashboard_subtitle": "إدارة إعدادات Demiurgos",
        "not_configured": "غير مُهيأ",
        "config_skipped": "تم التخطي",
        "config_coming_soon": "لوحة التهيئة الكاملة قريباً",
        "config_language": "اللغة",
        "config_world": "العالم",
        "config_ai": "الذكاء الاصطناعي للنص والرؤية",
        "config_images": "الصور",
        "config_chats": "الدردشات",
        "config_backup": "النسخ الاحتياطي",
        "restart_wizard": "إعادة تشغيل المعالج",
    },

    # ==================================================================
    # Bengali
    # ==================================================================
    "bn": {
        "welcome_title": "Demiurgos-এ স্বাগতম",
        "welcome_subtitle": "Hermes-এর জন্য আপনার কাহিনী ইঞ্জিন। চলুন সেটআপ করি।",
        "select_language": "আপনার ভাষা নির্বাচন করুন",
        "continue_button": "চালিয়ে যান",
        "other": "অন্যান্য",

        "world_title": "আপনার বিশ্ব",
        "world_subtitle": "প্রতিটি গাথার একটি ঘর প্রয়োজন। নতুন বিশ্ব তৈরি করুন বা বিদ্যমান লোড করুন।",
        "create_new_world": "নতুন বিশ্ব তৈরি করুন",
        "load_existing_world": "বিদ্যমান বিশ্ব লোড করুন",
        "world_name_label": "বিশ্বের নাম",
        "world_name_placeholder": "যেমন, থ্যালাসিয়া, বিস্মৃত গভীরতা…",
        "select_folder": "ফোল্ডার নির্বাচন করুন",
        "supported_formats": "সমর্থিত ফরম্যাট",
        "format_docx": ".docx (Word) — সম্পূর্ণ সমর্থিত",
        "format_md": ".md (Obsidian) — শীঘ্রই আসছে",
        "format_notion": "Notion রপ্তানি — শীঘ্রই আসছে",
        "format_pdf": "PDF — শীঘ্রই আসছে",

        "ai_title": "AI কনফিগার করুন",
        "ai_subtitle": "Demiurgos-কে আপনার LLM প্রদানকারীদের সাথে সংযুক্ত করুন। টেক্সট মডেল আবশ্যক; ভিশন ঐচ্ছিক।",
        "provider_label": "প্রদানকারী",
        "endpoint_label": "এন্ডপয়েন্ট URL",
        "api_key_label": "API কী",
        "model_text_label": "টেক্সট মডেল",
        "model_vision_label": "ভিশন মডেল",
        "test_connection": "সংযোগ পরীক্ষা করুন",
        "testing": "সংযোগ পরীক্ষা করা হচ্ছে…",
        "connection_success": "সংযোগ সফল — {count}টি মডেল পাওয়া গেছে",
        "connection_error": "সংযোগ ব্যর্থ",
        "same_as_text": "টেক্সট মডেলের মতোই",
        "vision_warning": "{model} ভিশন সমর্থন করে না। ভিশন কাজের জন্য 👁️ চিহ্নিত মডেল নির্বাচন করুন।",
        "save_config": "কনফিগারেশন সংরক্ষণ করুন",
        "select_model": "মডেল নির্বাচন করুন…",
        "select_provider": "প্রদানকারী নির্বাচন করুন…",
        "discover_models": "মডেল আবিষ্কার করুন",

        "images_title": "ছবি তৈরি",
        "images_subtitle": "ঐচ্ছিক — দৃশ্যকাহিনীর জন্য ছবি তৈরির প্রদানকারী কনফিগার করুন।",
        "skip_for_now": "এখন skip করুন",
        "configure_later": "পরে কনফিগার করুন",

        "chats_title": "চ্যাট প্ল্যাটফর্ম",
        "chats_subtitle": "ঐচ্ছিক — মোবাইল অ্যাক্সেসের জন্য Demiurgos-কে Telegram বা Discord-এ সংযুক্ত করুন।",

        "backup_title": "ব্যাকআপ ও সিঙ্ক",
        "backup_subtitle": "ঐচ্ছিক — আপনার বিশ্ব ও লোরের স্বয়ংক্রিয় ব্যাকআপ সেটআপ করুন।",

        "summary_title": "শুরু করার জন্য প্রস্তুত",
        "summary_subtitle": "এখানে আপনার কনফিগারেশনের সারসংক্ষেপ। আপনি পরে যেকোনো কিছু পরিবর্তন করতে পারবেন।",
        "start_using": "Demiurgos ব্যবহার শুরু করুন",
        "go_back": "ফিরে যান",
        "world_created": "বিশ্ব তৈরি হয়েছে",
        "ai_configured": "AI কনফিগার করা হয়েছে",
        "configured": "কনফিগার করা হয়েছে",
        "skipped": "বাদ দেওয়া হয়েছে",
        "edit": "সম্পাদনা",

        "next": "পরবর্তী",
        "back": "পূর্ববর্তী",
        "step_x_of_y": "ধাপ {current} / {total}",

        "error_generic": "কিছু ভুল হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন।",
        "error_required_field": "এই ক্ষেত্রটি আবশ্যক।",
        "error_connection": "সার্ভারে সংযোগ করা যায়নি। আপনার নেটওয়ার্ক পরীক্ষা করে আবার চেষ্টা করুন।",
        "error_timeout": "{seconds} সেকেন্ড পর সংযোগের সময় শেষ",
        "error_connect": "এন্ডপয়েন্টে পৌঁছানো যাচ্ছে না — URL পরীক্ষা করুন",
        "error_network": "নেটওয়ার্ক ত্রুটি",
        "error_auth_401": "অবৈধ API কী — আপনার শংসাপত্র পরীক্ষা করুন",
        "error_auth_403": "অ্যাক্সেস অস্বীকৃত — API কী অনুমতি পরীক্ষা করুন",
        "error_endpoint_404": "/models এন্ডপয়েন্ট পাওয়া যায়নি — URL কি সঠিক?",
        "error_server": "সার্ভার ত্রুটি (HTTP {code})",
        "error_json_parse": "সার্ভারের প্রতিক্রিয়া পড়তে পারেনি",
        "error_unexpected_format": "অপ্রত্যাশিত প্রতিক্রিয়া বিন্যাস",
        "error_no_models": "কোনো সামঞ্জস্যপূর্ণ টেক্সট/ইমেজ মডেল পাওয়া যায়নি",

        "vision_tag_confirmed": "👁️ ভিশন",
        "vision_tag_text_only": "✍️ টেক্সট",
        "vision_tag_unknown": "❓ অজানা",

        "world_name_hint": "ছোট হাতের অক্ষর, সংখ্যা এবং হাইফেন ব্যবহার করুন। যেমন: mi-mundo",
        "browse_button": "ব্রাউজ করুন...",
        "test_vision_connection": "ভিশন সংযোগ পরীক্ষা করুন",
        "images_explanation": "Demiurgos আপনার চরিত্র ও দৃশ্যের চিত্র তৈরি করতে পারে আপনার বিশ্বকে জীবন্ত করতে।",
        "save_and_continue": "সংরক্ষণ করুন এবং চালিয়ে যান",
        "chats_explanation": "আপনার ফোন থেকে লিখতে ও বিশ্ব পরিচালনা করতে Demiurgos-কে মেসেজিং অ্যাপে সংযুক্ত করুন।",
        "telegram": "Telegram",
        "discord": "Discord",
        "coming_soon": "শীঘ্রই আসছে",
        "backup_explanation": "আপনার বিশ্ব ও লোর স্বয়ংক্রিয়ভাবে Google Drive-এ সংরক্ষণ করুন।",
        "enable_backup": "স্বয়ংক্রিয় ব্যাকআপ সক্রিয় করুন",
        "rclone_warning": "Google Drive ব্যাকআপের জন্য rclone প্রয়োজন। প্রথমে এটি ইনস্টল করুন এবং 'rclone config' চালান।",
        "language_label": "ভাষা",
        "world_label": "বিশ্ব",
        "ai_text_label": "AI টেক্সট",
        "ai_vision_label": "AI ভিশন",
        "images_label": "ছবি তৈরি",
        "chats_label": "চ্যাট",
        "backup_label": "ব্যাকআপ",

        # -- সংযোগ/ত্রুটি টুকরো -------------------------------------------
        "connection_success_title": "সংযোগ সফল",
        "connection_success_detail": "{count}টি সামঞ্জস্যপূর্ণ মডেল পাওয়া গেছে।",
        "vision_connection_success_detail": "{count}টি ভিশন মডেল পাওয়া গেছে।",
        "model_select_placeholder": "— মডেল নির্বাচন করুন —",
        "model_custom_option": "অন্যান্য (ম্যানুয়ালি টাইপ করুন)",
        "vision_supported_notice": "প্রদানকারী ভিশন সমর্থন করে। {count}টি মডেল লোড হয়েছে।",
        "vision_not_supported_notice": "এই প্রদানকারী ভিশন সমর্থন করে না। ভিশন বিভাগ নিষ্ক্রিয়।",
        "error_title": "ত্রুটি",
        "error_dismiss_label": "বন্ধ করুন",
        "error_connection_hint": "এন্ডপয়েন্ট, API কী এবং ইন্টারনেট সংযোগ পরীক্ষা করুন।",
        "error_test_first": "— প্রথমে সংযোগ পরীক্ষা করুন —",

        # -- ব্যাকআপ স্ক্রিন ----------------------------------------------
        "backup_interval_label": "ব্যবধান",
        "backup_interval_hourly": "প্রতি ঘণ্টা",
        "backup_interval_daily": "প্রতিদিন",
        "backup_interval_weekly": "প্রতি সপ্তাহ",

        # -- চ্যাট স্ক্রিন -------------------------------------------------
        "bot_token_label": "Bot Token",
        "enable_chat_platform": "সক্রিয় করুন",

        # -- Dashboard / already-configured ------------------------------
        "already_configured_title": "Demiurgos ইতিমধ্যে কনফিগার করা আছে",
        "already_configured_subtitle": "আপনার LLM প্রদানকারী সেট আপ করা আছে। আপনার বিশ্বে যান বা পুনরায় কনফিগার করুন।",
        "continue_to_demiurgos": "Demiurgos-এ চালিয়ে যান",
        "reconfigure": "পুনরায় কনফিগার করুন",
        "config_dashboard_title": "কনফিগারেশন",
        "config_dashboard_subtitle": "আপনার Demiurgos সেটিংস পরিচালনা করুন",
        "not_configured": "কনফিগার করা হয়নি",
        "config_skipped": "বাদ দেওয়া হয়েছে",
        "config_coming_soon": "সম্পূর্ণ কনফিগারেশন প্যানেল শীঘ্রই আসছে",
        "config_language": "ভাষা",
        "config_world": "বিশ্ব",
        "config_ai": "AI টেক্সট ও ভিশন",
        "config_images": "ছবি",
        "config_chats": "চ্যাট",
        "config_backup": "ব্যাকআপ",
        "restart_wizard": "উইজার্ড পুনরায় শুরু করুন",
    },

    # ==================================================================
    # Portuguese
    # ==================================================================
    "pt": {
        "welcome_title": "Bem-vindo ao Demiurgos",
        "welcome_subtitle": "Seu motor narrativo para o Hermes. Vamos configurar.",
        "select_language": "Escolha seu idioma",
        "continue_button": "Continuar",
        "other": "Outro",

        "world_title": "Seu Mundo",
        "world_subtitle": "Toda saga precisa de um lar. Crie um novo mundo ou carregue um existente.",
        "create_new_world": "Criar Novo Mundo",
        "load_existing_world": "Carregar Mundo Existente",
        "world_name_label": "Nome do mundo",
        "world_name_placeholder": "ex., Thalassia, As Profundezas Esquecidas…",
        "select_folder": "Selecionar pasta",
        "supported_formats": "Formatos suportados",
        "format_docx": ".docx (Word) — totalmente suportado",
        "format_md": ".md (Obsidian) — em breve",
        "format_notion": "Exportação do Notion — em breve",
        "format_pdf": "PDF — em breve",

        "ai_title": "Configurar IA",
        "ai_subtitle": "Conecte o Demiurgos aos seus provedores LLM. O modelo de texto é obrigatório; visão é opcional.",
        "provider_label": "Provedor",
        "endpoint_label": "URL do endpoint",
        "api_key_label": "Chave API",
        "model_text_label": "Modelo de texto",
        "model_vision_label": "Modelo de visão",
        "test_connection": "Testar Conexão",
        "testing": "Testando conexão…",
        "connection_success": "Conexão bem-sucedida — {count} modelos encontrados",
        "connection_error": "Falha na conexão",
        "same_as_text": "Mesmo que modelo de texto",
        "vision_warning": "{model} não suporta visão. Escolha um modelo marcado com 👁️ para tarefas de visão.",
        "save_config": "Salvar Configuração",
        "select_model": "Selecione um modelo…",
        "select_provider": "Selecione um provedor…",
        "discover_models": "Descobrir modelos",

        "images_title": "Geração de Imagens",
        "images_subtitle": "Opcional — configure um provedor de imagens para narrativa visual.",
        "skip_for_now": "Pular por enquanto",
        "configure_later": "Configurar depois",

        "chats_title": "Plataformas de Chat",
        "chats_subtitle": "Opcional — conecte o Demiurgos ao Telegram ou Discord para acesso móvel.",

        "backup_title": "Backup e Sincronização",
        "backup_subtitle": "Opcional — configure backups automáticos dos seus mundos e lore.",

        "summary_title": "Pronto para Começar",
        "summary_subtitle": "Aqui está um resumo da sua configuração. Você pode alterar tudo depois.",
        "start_using": "Começar a Usar o Demiurgos",
        "go_back": "Voltar",
        "world_created": "Mundo criado",
        "ai_configured": "IA configurada",
        "configured": "Configurado",
        "skipped": "Pulado",
        "edit": "Editar",

        "next": "Próximo",
        "back": "Anterior",
        "step_x_of_y": "Etapa {current} de {total}",

        "error_generic": "Algo deu errado. Tente novamente.",
        "error_required_field": "Este campo é obrigatório.",
        "error_connection": "Não foi possível conectar ao servidor. Verifique sua rede e tente novamente.",
        "error_timeout": "Conexão expirou após {seconds}s",
        "error_connect": "Endpoint inacessível — verifique a URL",
        "error_network": "Erro de rede",
        "error_auth_401": "Chave API inválida — verifique suas credenciais",
        "error_auth_403": "Acesso negado — verifique as permissões da chave API",
        "error_endpoint_404": "Endpoint /models não encontrado — a URL está correta?",
        "error_server": "Erro do servidor (HTTP {code})",
        "error_json_parse": "Não foi possível ler a resposta do servidor",
        "error_unexpected_format": "Formato de resposta inesperado",
        "error_no_models": "Nenhum modelo de texto/imagem compatível encontrado",

        "vision_tag_confirmed": "👁️ visão",
        "vision_tag_text_only": "✍️ texto",
        "vision_tag_unknown": "❓ desconhecido",

        "world_name_hint": "Use letras minúsculas, números e hífens. Ex.: mi-mundo",
        "browse_button": "Navegar...",
        "test_vision_connection": "Testar Conexão de Visão",
        "images_explanation": "O Demiurgos pode criar ilustrações dos seus personagens e cenas para dar vida ao seu mundo.",
        "save_and_continue": "Salvar e Continuar",
        "chats_explanation": "Conecte o Demiurgos aos seus aplicativos de mensagens para escrever e gerenciar seu mundo pelo celular.",
        "telegram": "Telegram",
        "discord": "Discord",
        "coming_soon": "Em breve",
        "backup_explanation": "Salve seu mundo e lore automaticamente no Google Drive para nunca perder seu trabalho.",
        "enable_backup": "Ativar backup automático",
        "rclone_warning": "rclone é necessário para backup no Google Drive. Instale-o e execute 'rclone config' primeiro.",
        "language_label": "Idioma",
        "world_label": "Mundo",
        "ai_text_label": "IA de Texto",
        "ai_vision_label": "IA de Visão",
        "images_label": "Geração de Imagens",
        "chats_label": "Chats",
        "backup_label": "Backup",

        # -- Fragmentos de conexão/erro ----------------------------------
        "connection_success_title": "Conexão bem-sucedida",
        "connection_success_detail": "{count} modelos compatíveis descobertos.",
        "vision_connection_success_detail": "{count} modelos de visão descobertos.",
        "model_select_placeholder": "— Selecione um modelo —",
        "model_custom_option": "Outro (digitar manualmente)",
        "vision_supported_notice": "O provedor suporta visão. {count} modelos carregados.",
        "vision_not_supported_notice": "Este provedor não suporta visão. Seção de visão desativada.",
        "error_title": "Erro",
        "error_dismiss_label": "Fechar",
        "error_connection_hint": "Verifique o endpoint, a chave API e sua conexão com a internet.",
        "error_test_first": "— Teste a conexão primeiro —",

        # -- Tela de backup ----------------------------------------------
        "backup_interval_label": "Intervalo",
        "backup_interval_hourly": "A cada hora",
        "backup_interval_daily": "Todos os dias",
        "backup_interval_weekly": "Toda semana",

        # -- Tela de chats -----------------------------------------------
        "bot_token_label": "Bot Token",
        "enable_chat_platform": "Ativar",

        # -- Dashboard / already-configured ------------------------------
        "already_configured_title": "Demiurgos já está configurado",
        "already_configured_subtitle": "Seu provedor LLM está configurado. Continue para seu mundo ou reconfigure.",
        "continue_to_demiurgos": "Continuar para o Demiurgos",
        "reconfigure": "Reconfigurar",
        "config_dashboard_title": "Configuração",
        "config_dashboard_subtitle": "Gerencie suas configurações do Demiurgos",
        "not_configured": "Não configurado",
        "config_skipped": "Pulado",
        "config_coming_soon": "Painel de configuração completo em breve",
        "config_language": "Idioma",
        "config_world": "Mundo",
        "config_ai": "IA Texto e Visão",
        "config_images": "Imagens",
        "config_chats": "Chats",
        "config_backup": "Backup",
        "restart_wizard": "Reiniciar Assistente",
    },

    # ==================================================================
    # Russian
    # ==================================================================
    "ru": {
        "welcome_title": "Добро пожаловать в Demiurgos",
        "welcome_subtitle": "Ваш нарративный движок для Hermes. Давайте настроим всё.",
        "select_language": "Выберите язык",
        "continue_button": "Продолжить",
        "other": "Другой",

        "world_title": "Ваш Мир",
        "world_subtitle": "Каждой саге нужен дом. Создайте новый мир или загрузите существующий.",
        "create_new_world": "Создать Новый Мир",
        "load_existing_world": "Загрузить Существующий Мир",
        "world_name_label": "Название мира",
        "world_name_placeholder": "напр., Талассия, Забытые Глубины…",
        "select_folder": "Выбрать папку",
        "supported_formats": "Поддерживаемые форматы",
        "format_docx": ".docx (Word) — полностью поддерживается",
        "format_md": ".md (Obsidian) — скоро",
        "format_notion": "Экспорт из Notion — скоро",
        "format_pdf": "PDF — скоро",

        "ai_title": "Настройка ИИ",
        "ai_subtitle": "Подключите Demiurgos к вашим LLM-провайдерам. Текстовая модель обязательна; зрение — опционально.",
        "provider_label": "Провайдер",
        "endpoint_label": "URL эндпоинта",
        "api_key_label": "API-ключ",
        "model_text_label": "Текстовая модель",
        "model_vision_label": "Модель зрения",
        "test_connection": "Проверить Соединение",
        "testing": "Проверка соединения…",
        "connection_success": "Соединение успешно — найдено {count} моделей",
        "connection_error": "Ошибка соединения",
        "same_as_text": "Как текстовая модель",
        "vision_warning": "{model} не поддерживает зрение. Выберите модель с 👁️ для задач со зрением.",
        "save_config": "Сохранить Конфигурацию",
        "select_model": "Выберите модель…",
        "select_provider": "Выберите провайдера…",
        "discover_models": "Найти модели",

        "images_title": "Генерация Изображений",
        "images_subtitle": "Опционально — настройте провайдера изображений для визуального повествования.",
        "skip_for_now": "Пропустить",
        "configure_later": "Настроить позже",

        "chats_title": "Чат-Платформы",
        "chats_subtitle": "Опционально — подключите Demiurgos к Telegram или Discord для мобильного доступа.",

        "backup_title": "Резервное Копирование",
        "backup_subtitle": "Опционально — настройте автоматическое резервное копирование миров и лора.",

        "summary_title": "Готовы к Началу",
        "summary_subtitle": "Вот сводка вашей конфигурации. Всё можно изменить позже.",
        "start_using": "Начать Использовать Demiurgos",
        "go_back": "Назад",
        "world_created": "Мир создан",
        "ai_configured": "ИИ настроен",
        "configured": "Настроено",
        "skipped": "Пропущено",
        "edit": "Изменить",

        "next": "Далее",
        "back": "Назад",
        "step_x_of_y": "Шаг {current} из {total}",

        "error_generic": "Что-то пошло не так. Попробуйте снова.",
        "error_required_field": "Это поле обязательно для заполнения.",
        "error_connection": "Не удалось подключиться к серверу. Проверьте сеть и попробуйте снова.",
        "error_timeout": "Тайм-аут соединения через {seconds} сек.",
        "error_connect": "Недоступный эндпоинт — проверьте URL",
        "error_network": "Ошибка сети",
        "error_auth_401": "Неверный API-ключ — проверьте учетные данные",
        "error_auth_403": "Доступ запрещен — проверьте разрешения API-ключа",
        "error_endpoint_404": "Эндпоинт /models не найден — правильный ли URL?",
        "error_server": "Ошибка сервера (HTTP {code})",
        "error_json_parse": "Не удалось прочитать ответ сервера",
        "error_unexpected_format": "Неожиданный формат ответа",
        "error_no_models": "Совместимые модели текст/изображение не найдены",

        "vision_tag_confirmed": "👁️ зрение",
        "vision_tag_text_only": "✍️ текст",
        "vision_tag_unknown": "❓ неизвестно",

        "world_name_hint": "Используйте строчные буквы, цифры и дефисы. Напр.: mi-mundo",
        "browse_button": "Обзор...",
        "test_vision_connection": "Проверить Соединение Зрения",
        "images_explanation": "Demiurgos может создавать иллюстрации ваших персонажей и сцен, чтобы оживить ваш мир.",
        "save_and_continue": "Сохранить и Продолжить",
        "chats_explanation": "Подключите Demiurgos к вашим мессенджерам, чтобы писать и управлять миром с телефона.",
        "telegram": "Telegram",
        "discord": "Discord",
        "coming_soon": "Скоро",
        "backup_explanation": "Автоматически сохраняйте ваш мир и лор на Google Drive.",
        "enable_backup": "Включить автобэкап",
        "rclone_warning": "Для бэкапа на Google Drive требуется rclone. Установите и запустите 'rclone config' сначала.",
        "language_label": "Язык",
        "world_label": "Мир",
        "ai_text_label": "ИИ Текст",
        "ai_vision_label": "ИИ Зрение",
        "images_label": "Генерация Изображений",
        "chats_label": "Чаты",
        "backup_label": "Бэкап",

        # -- Фрагменты соединения/ошибки ----------------------------------
        "connection_success_title": "Соединение успешно",
        "connection_success_detail": "Найдено {count} совместимых моделей.",
        "vision_connection_success_detail": "Найдено {count} моделей зрения.",
        "model_select_placeholder": "— Выберите модель —",
        "model_custom_option": "Другая (ввести вручную)",
        "vision_supported_notice": "Провайдер поддерживает зрение. Загружено {count} моделей.",
        "vision_not_supported_notice": "Этот провайдер не поддерживает зрение. Раздел зрения отключён.",
        "error_title": "Ошибка",
        "error_dismiss_label": "Закрыть",
        "error_connection_hint": "Проверьте эндпоинт, API-ключ и подключение к интернету.",
        "error_test_first": "— Сначала проверьте соединение —",

        # -- Экран бэкапа ------------------------------------------------
        "backup_interval_label": "Интервал",
        "backup_interval_hourly": "Каждый час",
        "backup_interval_daily": "Каждый день",
        "backup_interval_weekly": "Каждую неделю",

        # -- Экран чатов -------------------------------------------------
        "bot_token_label": "Bot Token",
        "enable_chat_platform": "Включить",

        # -- Dashboard / already-configured ------------------------------
        "already_configured_title": "Demiurgos уже настроен",
        "already_configured_subtitle": "Ваш LLM-провайдер настроен. Перейдите к своему миру или перенастройте.",
        "continue_to_demiurgos": "Перейти к Demiurgos",
        "reconfigure": "Перенастроить",
        "config_dashboard_title": "Конфигурация",
        "config_dashboard_subtitle": "Управление настройками Demiurgos",
        "not_configured": "Не настроено",
        "config_skipped": "Пропущено",
        "config_coming_soon": "Полная панель конфигурации скоро будет доступна",
        "config_language": "Язык",
        "config_world": "Мир",
        "config_ai": "ИИ Текст и Зрение",
        "config_images": "Изображения",
        "config_chats": "Чаты",
        "config_backup": "Бэкап",
        "restart_wizard": "Перезапустить мастер",
    },

    # ==================================================================
    # Urdu
    # ==================================================================
    "ur": {
        "welcome_title": "Demiurgos میں خوش آمدید",
        "welcome_subtitle": "Hermes کے لیے آپ کا کہانی انجن۔ آئیے سیٹ اپ کرتے ہیں۔",
        "select_language": "اپنی زبان منتخب کریں",
        "continue_button": "جاری رکھیں",
        "other": "دیگر",

        "world_title": "آپ کی دنیا",
        "world_subtitle": "ہر کہانی کو ایک گھر چاہیے۔ نئی دنیا بنائیں یا موجودہ لوڈ کریں۔",
        "create_new_world": "نئی دنیا بنائیں",
        "load_existing_world": "موجودہ دنیا لوڈ کریں",
        "world_name_label": "دنیا کا نام",
        "world_name_placeholder": "مثلاً، تھیلیسیا، بھولی ہوئی گہرائیاں…",
        "select_folder": "فولڈر منتخب کریں",
        "supported_formats": "تعاون یافتہ فارمیٹس",
        "format_docx": ".docx (Word) — مکمل تعاون یافتہ",
        "format_md": ".md (Obsidian) — جلد آرہا ہے",
        "format_notion": "Notion ایکسپورٹ — جلد آرہا ہے",
        "format_pdf": "PDF — جلد آرہا ہے",

        "ai_title": "AI ترتیب دیں",
        "ai_subtitle": "Demiurgos کو اپنے LLM فراہم کنندگان سے جوڑیں۔ ٹیکسٹ ماڈل ضروری ہے؛ ویژن اختیاری ہے۔",
        "provider_label": "فراہم کنندہ",
        "endpoint_label": "اینڈپوائنٹ URL",
        "api_key_label": "API کلید",
        "model_text_label": "ٹیکسٹ ماڈل",
        "model_vision_label": "ویژن ماڈل",
        "test_connection": "کنکشن ٹیسٹ کریں",
        "testing": "کنکشن ٹیسٹ ہو رہا ہے…",
        "connection_success": "کنکشن کامیاب — {count} ماڈل ملے",
        "connection_error": "کنکشن ناکام",
        "same_as_text": "ٹیکسٹ ماڈل جیسا ہی",
        "vision_warning": "{model} ویژن کو سپورٹ نہیں کرتا۔ ویژن کاموں کے لیے 👁️ نشان والا ماڈل منتخب کریں۔",
        "save_config": "ترتیب محفوظ کریں",
        "select_model": "ماڈل منتخب کریں…",
        "select_provider": "فراہم کنندہ منتخب کریں…",
        "discover_models": "ماڈل دریافت کریں",

        "images_title": "تصویر سازی",
        "images_subtitle": "اختیاری — بصری کہانی کے لیے تصویر سازی کا فراہم کنندہ ترتیب دیں۔",
        "skip_for_now": "ابھی چھوڑیں",
        "configure_later": "بعد میں ترتیب دیں",

        "chats_title": "چیٹ پلیٹ فارم",
        "chats_subtitle": "اختیاری — موبائل رسائی کے لیے Demiurgos کو Telegram یا Discord سے جوڑیں۔",

        "backup_title": "بیک اپ اور سنک",
        "backup_subtitle": "اختیاری — اپنی دنیاؤں اور لور کا خودکار بیک اپ سیٹ کریں۔",

        "summary_title": "شروع کرنے کے لیے تیار",
        "summary_subtitle": "یہاں آپ کی ترتیب کا خلاصہ ہے۔ آپ بعد میں کچھ بھی تبدیل کر سکتے ہیں۔",
        "start_using": "Demiurgos استعمال کرنا شروع کریں",
        "go_back": "واپس جائیں",
        "world_created": "دنیا بن گئی",
        "ai_configured": "AI ترتیب دی گئی",
        "configured": "ترتیب شدہ",
        "skipped": "چھوڑ دیا گیا",
        "edit": "ترمیم کریں",

        "next": "اگلا",
        "back": "پچھلا",
        "step_x_of_y": "مرحلہ {current} / {total}",

        "error_generic": "کچھ غلط ہو گیا۔ براہ کرم دوبارہ کوشش کریں۔",
        "error_required_field": "یہ فیلڈ ضروری ہے۔",
        "error_connection": "سرور سے رابطہ نہیں ہو سکا۔ اپنا نیٹ ورک چیک کریں اور دوبارہ کوشش کریں۔",
        "error_timeout": "{seconds} سیکنڈ کے بعد کنکشن کا وقت ختم",
        "error_connect": "اینڈپوائنٹ تک نہیں پہنچ سکتے — URL چیک کریں",
        "error_network": "نیٹ ورک کی خرابی",
        "error_auth_401": "غلط API کلید — اپنی اسناد چیک کریں",
        "error_auth_403": "رسائی مسترد — API کلید کی اجازتیں چیک کریں",
        "error_endpoint_404": "/models اینڈپوائنٹ نہیں ملا — کیا URL درست ہے؟",
        "error_server": "سرور کی خرابی (HTTP {code})",
        "error_json_parse": "سرور کا جواب نہیں پڑھ سکے",
        "error_unexpected_format": "غیر متوقع جوابی فارمیٹ",
        "error_no_models": "کوئی مطابقت پذیر ٹیکسٹ/امیج ماڈل نہیں ملا",

        "vision_tag_confirmed": "👁️ ویژن",
        "vision_tag_text_only": "✍️ ٹیکسٹ",
        "vision_tag_unknown": "❓ نامعلوم",

        "world_name_hint": "چھوٹے حروف، اعداد اور ڈیش استعمال کریں۔ مثال: mi-mundo",
        "browse_button": "براؤز کریں...",
        "test_vision_connection": "ویژن کنکشن ٹیسٹ کریں",
        "images_explanation": "Demiurgos آپ کے کرداروں اور مناظر کی تصاویر بنا سکتا ہے۔",
        "save_and_continue": "محفوظ کریں اور جاری رکھیں",
        "chats_explanation": "اپنے فون سے لکھنے اور دنیا کا انتظام کرنے کے لیے Demiurgos کو میسجنگ ایپس سے جوڑیں۔",
        "telegram": "Telegram",
        "discord": "Discord",
        "coming_soon": "جلد آرہا ہے",
        "backup_explanation": "اپنی دنیا اور لور کو خودکار طور پر Google Drive پر محفوظ کریں۔",
        "enable_backup": "خودکار بیک اپ فعال کریں",
        "rclone_warning": "Google Drive بیک اپ کے لیے rclone ضروری ہے۔ براہ کرم اسے انسٹال کریں اور 'rclone config' چلائیں۔",
        "language_label": "زبان",
        "world_label": "دنیا",
        "ai_text_label": "AI ٹیکسٹ",
        "ai_vision_label": "AI ویژن",
        "images_label": "تصویر سازی",
        "chats_label": "چیٹس",
        "backup_label": "بیک اپ",

        # -- کنکشن/خرابی کے ٹکڑے -----------------------------------------
        "connection_success_title": "کنکشن کامیاب",
        "connection_success_detail": "{count} ہم آہنگ ماڈل دریافت ہوئے۔",
        "vision_connection_success_detail": "{count} ویژن ماڈل دریافت ہوئے۔",
        "model_select_placeholder": "— ماڈل منتخب کریں —",
        "model_custom_option": "دیگر (دستی طور پر ٹائپ کریں)",
        "vision_supported_notice": "فراہم کنندہ ویژن کو سپورٹ کرتا ہے۔ {count} ماڈل لوڈ ہوئے۔",
        "vision_not_supported_notice": "یہ فراہم کنندہ ویژن کو سپورٹ نہیں کرتا۔ ویژن سیکشن غیر فعال۔",
        "error_title": "خرابی",
        "error_dismiss_label": "بند کریں",
        "error_connection_hint": "اینڈپوائنٹ، API کلید اور انٹرنیٹ کنکشن چیک کریں۔",
        "error_test_first": "— پہلے کنکشن ٹیسٹ کریں —",

        # -- بیک اپ اسکرین -----------------------------------------------
        "backup_interval_label": "وقفہ",
        "backup_interval_hourly": "ہر گھنٹے",
        "backup_interval_daily": "ہر روز",
        "backup_interval_weekly": "ہر ہفتے",

        # -- چیٹ اسکرین --------------------------------------------------
        "bot_token_label": "Bot Token",
        "enable_chat_platform": "فعال کریں",

        # -- Dashboard / already-configured ------------------------------
        "already_configured_title": "Demiurgos پہلے سے ترتیب شدہ ہے",
        "already_configured_subtitle": "آپ کا LLM فراہم کنندہ سیٹ ہے۔ اپنی دنیا میں جائیں یا دوبارہ ترتیب دیں۔",
        "continue_to_demiurgos": "Demiurgos پر جاری رکھیں",
        "reconfigure": "دوبارہ ترتیب دیں",
        "config_dashboard_title": "ترتیب",
        "config_dashboard_subtitle": "اپنی Demiurgos ترتیبات کا انتظام کریں",
        "not_configured": "ترتیب شدہ نہیں",
        "config_skipped": "چھوڑ دیا گیا",
        "config_coming_soon": "مکمل ترتیبات کا پینل جلد آرہا ہے",
        "config_language": "زبان",
        "config_world": "دنیا",
        "config_ai": "AI ٹیکسٹ اور ویژن",
        "config_images": "تصاویر",
        "config_chats": "چیٹس",
        "config_backup": "بیک اپ",
        "restart_wizard": "وزرڈ دوبارہ شروع کریں",
    },
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def t(lang: str, key: str) -> str:
    """Return the translation for *key* in *lang*, with safe fallback.

    Fallback chain (first match wins):
    1.  Exact match in requested language
    2.  English fallback for the same key
    3.  The *key* string itself (never returns empty string)

    Examples::

        >>> t("es-ar", "welcome_title")
        'Bienvenido a Demiurgos'

        >>> t("es", "welcome_title")
        'Bienvenido a Demiurgos'

        >>> t("zz", "welcome_title")       # unknown lang → English
        'Welcome to Demiurgos'

        >>> t("en", "nonexistent_key")
        'nonexistent_key'
    """
    lang_dict = _LANGUAGES.get(lang)

    # Exact match in requested language
    if lang_dict is not None:
        value = lang_dict.get(key)
        if value is not None:
            return value

    # Fallback to English
    en_dict = _LANGUAGES.get(_FALLBACK_LANG, {})
    value = en_dict.get(key)
    if value is not None:
        return value

    # Last resort: return the key itself (never crash, never empty)
    return key


def get_text(key: str, lang: str) -> str:
    """Alias for :func:`t` with *key* first, for callers that prefer that order.

    Equivalent to ``t(lang, key)``.
    """
    return t(lang, key)


def get_language_name(lang_code: str) -> str:
    """Return the human-readable name for *lang_code* in that language.

    If the code is unknown, returns the code itself.

    Examples::

        >>> get_language_name("es-ar")
        'Español (Argentina)'

        >>> get_language_name("en")
        'English'
    """
    return _LANGUAGE_NAMES.get(lang_code, lang_code)


def available_languages() -> list[str]:
    """Return the list of supported language codes, in definition order."""
    return list(_LANGUAGES.keys())


# ---------------------------------------------------------------------------
# Jinja2 integration
# ---------------------------------------------------------------------------


def register_with_jinja(
    templates: object,
    lang_getter: Callable[[], str],
) -> None:
    """Register ``t(key)`` and ``lang_name()`` as template globals.

    *templates* must be a ``jinja2.Environment`` or any object that exposes a
    ``.globals`` dict (such as FastAPI's ``Jinja2Templates().env``).

    *lang_getter* is a zero-argument callable that returns the current
    language code for the request (e.g. ``lambda: session["language"]``).

    After registration, templates can use::

        {{ t("welcome_title") }}
        {{ lang_name() }}
        {{ t("step_x_of_y", current=2, total=7) }}

    Usage in ``main.py``::

        from i18n import register_with_jinja
        register_with_jinja(templates.env, lambda: request.state.language)
    """
    env = getattr(templates, "env", templates)

    def _t(key: str, **fmt_kwargs: object) -> str:
        text = t(lang_getter(), key)
        if fmt_kwargs:
            return text.format(**fmt_kwargs)
        return text

    env.globals["t"] = _t
    env.globals["lang_name"] = lambda: get_language_name(lang_getter())
