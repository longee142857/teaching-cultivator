/* Bilingual copy for the static showcase. Chinese is the default text in HTML. */
(function () {
  var STR = {
    zh: {
      skip: "跳到正文",
      brand: "考研培养",
      "aria.nav": "页面",
      "aria.lang": "语言",
      "aria.style": "样式",
      "aria.layout": "示意屏排列",
      "aria.screens": "示意屏",
      "nav.home": "首页",
      "nav.product": "产品",
      "nav.gallery": "样式",
      "nav.how": "如何工作",
      "nav.contact": "联系",
      "style.desk": "练习台",
      "style.studio": "工作室",
      "demo.toast": "示意按钮，不会提交，也不会联网。",
      "foot.note": "公开示意站。没有学员姓名、编号、令牌或会话。",
      "foot.repo": "仓库",
      "title.home": "考研培养 · teaching-cultivator",
      "desc.home": "服务学员的考研培养代理：日程练习、反馈闭环、钉钉通知，以及练习台与工作室两种样式。示意站，不含学员资料。",
      "home.eyebrow": "服务学员的代理",
      "home.h1": "按时练习，收回反馈，再出下一题。",
      "home.lede": "teaching-cultivator 按日程服务学员：数学，再加上一门或多门可配置的其他科目。示意里的第二科写成通信，只是例子。钉钉送达短通知，作答和讲解在练习台完成。可选 Android「反馈出题机」走同一条闭环。本站展示样式与流程，题干和数字都是占位。",
      "home.ctaGallery": "看两种样式",
      "home.ctaProduct": "产品说明",
      "home.ctaContact": "定制与 yaml",
      "home.f1t": "日程练习",
      "home.f1b": "早上和下午分科推送，晚上复习。数学和所配置的其他科目从已就绪的题库抽取；晚间复习在发送时当场生成。",
      "home.f2t": "反馈闭环",
      "home.f2b": "作答之后给出步骤反馈，掌握度写回考纲，供下一次选题。本站上的数字都是画出来的。",
      "home.f3t": "钉钉送达",
      "home.f3b": "即时消息里放短通知和练习深链。答题和讲解留在练习台，不堆进会话。",
      "home.f4t": "可选外壳",
      "home.f4b": "Android「反馈出题机」沿用答一题、看反馈、再出一题的路径。示意站不提供安装包。",
      "home.privacy": "本站没有真实姓名、学员编号、令牌或会话 ID。题干均为示意。",
      "home.demo": "公开练习入口（演示）",
      "home.demo2": "链接不附带令牌，也不能代替你自己的访问配置。",
      "title.product": "产品 · 考研培养",
      "desc.product": "面向学员的培养代理：数学，以及一门或多门可配置科目。示意里的第二科是通信。钉钉通知，练习台与可选的反馈出题机。不含学员进度。",
      "prod.eyebrow": "产品",
      "prod.h1": "数学，加上可配置的其他科目。",
      "prod.lede": "代理按日程决定今天练什么，有教材证据时才命题，用钉钉把人叫到练习台，批改后再把掌握度写回去。数学之外，还可以配置一门或多门其他科目。",
      "prod.tracksT": "科目",
      "prod.mathT": "数学",
      "prod.mathB": "考研数学向的日常练习。",
      "prod.commT": "其他科目（示例：通信）",
      "prod.commB": "第二门以及更多科目可以配置。示意里用通信类专业课举例。",
      "prod.tracksNote": "这里不展示任何人的进度。示意里的通信只是可配置科目的例子。",
      "prod.surfT": "三处表面",
      "prod.s1t": "练习台",
      "prod.s1b": "纸色页面：题干卡片、批改条、折叠讲解，以及「不懂，问讲师」。",
      "prod.s2t": "钉钉",
      "prod.s2b": "短通知和通往练习台的链接。",
      "prod.s3t": "反馈出题机",
      "prod.s3b": "可选的 Android 外壳，主路径与练习台相同。示意站不提供安装包。",
      "prod.gateT": "证据闸",
      "prod.gateB": "教材证据不够时，默认不硬出题。",
      "prod.outT": "本站放不上的东西",
      "prod.outB": "这里没有学员名单、成绩单、密钥或生产接口。运行时还可以组双周练习卷；本站不放卷面。",
      "prod.scopeT": "可以讨论的范围",
      "prod.scopeB": "现有链路上的配置：时段、要练的科目、通知文案，以及练习台或工作室的皮肤。科目按你所教的来定，不限于示意里的通信。",
      "title.gallery": "样式 · 练习台与工作室",
      "desc.gallery": "练习台（暖纸色）与工作室（冷地面、硬边、绯红）的 CSS 示意屏，可并排或单屏切换。不是学员截图。",
      "gal.eyebrow": "样式",
      "gal.h1": "暖纸色，或冷地面。",
      "gal.lede": "练习台是暖纸色：宣纸底、衬线标题、青灰强调、轻微纸纹。工作室是冷色地面、直角、绯红标记。屏幕都是 CSS 示意，不是学员截图。",
      "gal.help": "页眉的「练习台 / 工作室」会换整页皮肤。下面两块示意屏各用各的颜色。选「单屏」时，放大当前这种。",
      "gal.pair": "并排",
      "gal.focus": "单屏",
      "gal.queue": "今日队列",
      "gal.answer": "作答",
      "gal.feedback": "反馈",
      "gal.tutor": "讲师",
      "gal.notice": "通知",
      "gal.shell": "外壳",
      "title.how": "如何工作 · 考研培养",
      "desc.how": "从日程、选题、命题、钉钉送达，到批改和掌握度回写。只写公开流程，不写密钥和接口。",
      "how.eyebrow": "如何工作",
      "how.h1": "日程走到回写，中间有一道证据闸。",
      "how.lede": "下面是学员能感知到的路径。内部开关、密钥和接口留在运行环境里。",
      "how.s1t": "日程",
      "how.s1b": "早上和下午分科推送，晚上复习。数学和所配置的其他科目从已就绪的题库抽取；晚间复习在发送时当场生成。",
      "how.s2t": "选题",
      "how.s2b": "按考纲上的权重和掌握度挑选，并避开刚练过的点。",
      "how.s3t": "命题",
      "how.s3b": "有教材证据才写题。证据不够就停，不硬编。",
      "how.s4t": "送达",
      "how.s4b": "钉钉收到短通知和通往练习台的链接。作答不堆在会话里。",
      "how.s5t": "批改",
      "how.s5b": "对照题面给出步骤反馈。",
      "how.s6t": "回写",
      "how.s6b": "掌握度回到考纲，下一次选题能用上。",
      "how.where": "学员实际点击的地方，是练习台或反馈出题机。通知只负责把人带到那里。",
      "how.secretT": "配置留在运行环境",
      "how.secretB": "令牌、会话和学员编号留在运行环境里，不出现在这个网站上。",
      "title.contact": "联系 · 考研培养",
      "desc.contact": "核心 yaml 与定制请邮件 longee142857@qq.com。钉钉群定制服务不在本页公布群号。",
      "con.eyebrow": "联系",
      "con.h1": "核心 yaml 与定制，写信来。",
      "con.lede": "写明你要教的科目，以及希望改动的行为。科目不限于示意里的通信。定制服务在钉钉群里继续。",
      "con.mailT": "邮件",
      "con.mailB": "点地址即可写信。主题里写上你要教的科目，一门或多门都可以。",
      "con.groupT": "钉钉群",
      "con.groupB": "定制服务在钉钉群里进行。邮件说明需求后，再邀请进群。本页不公布群号。",
      "con.yamlT": "核心 yaml",
      "con.yamlB": "核心 yaml 与现有培养配置可以来信讨论。请不要附带令牌或学员编号。",
      "con.noT": "请不要发送",
      "con.noB": "令牌、学员编号、会话 ID、真实答卷。",
      "con.swatchDesk": "暖纸色 · 青灰",
      "con.swatchStudio": "冷地面 · 绯红",
      "mock.ribbon": "示意",
      "mock.appName": "高校每日练习",
      "mock.shellName": "反馈出题机",
      "mock.today": "今日三槽",
      "mock.math": "数学",
      "mock.comm": "通信",
      "mock.review": "复习",
      "mock.morning": "上午",
      "mock.afternoon": "下午",
      "mock.evening": "晚上",
      "mock.kpLimit": "示意考点 · 极限",
      "mock.kpBase": "示意考点 · 基带",
      "mock.kpReview": "示意考点 · 复习",
      "mock.open": "未作答",
      "mock.live": "当场生成",
      "mock.hintQueue": "数学、通信、复习各一题。通信是可配置科目的示意例子。过点未做的仍可补。此处全部为占位。",
      "mock.tabPractice": "练习",
      "mock.tabExam": "周卷",
      "mock.tabNotes": "资料",
      "mock.tabTutor": "讲师",
      "mock.stemEyebrow": "示意题干 · 数学",
      "mock.stemTitle": "反常积分是否收敛",
      "mock.stemMath": "占位题：判断 ∫ 从 0 到 ∞ 的 x²e^(−x) dx 是否收敛，并写出你用来判断的那一步。",
      "mock.stemCommEyebrow": "示意题干 · 通信（示例科目）",
      "mock.stemComm": "占位题：带限信道里，符号间隔小于奈奎斯特间隔时会发生什么？用一句话回答。",
      "mock.answerHint": "在这里写步骤。提交按钮不会联网。",
      "mock.submit": "提交",
      "mock.ask": "不懂，问讲师",
      "mock.partial": "部分正确",
      "mock.step1": "收敛的方向判断是对的。",
      "mock.step2": "上限只写了「趋于零」，还缺比较或分部的依据。",
      "mock.mastery": "示意掌握度 0.42 → 0.48",
      "mock.masteryNote": "这个数字是画出来的，不对应任何人。",
      "mock.next": "再出一题",
      "mock.you": "你",
      "mock.tutor": "讲师",
      "mock.tutor1": "占位对话。我只看见题干里的「比较」，没有学员档案。",
      "mock.user1": "我用了比较判别法，但没写出比较函数。",
      "mock.tutor2": "补一个拿来比较的函数，并写明不等式方向。",
      "mock.askMore": "继续问（示意）",
      "mock.noticeKicker": "钉钉 · 通知示意",
      "mock.noticeTitle": "今日练习已备好",
      "mock.noticeBody": "数学 1 题。打开练习台作答。讲解留在练习台，不写进这条消息。",
      "mock.openDesk": "打开练习台",
      "mock.noId": "无会话编号 · 无学员编号",
      "mock.loop": "答一题 → 看反馈 → 再出一题",
      "mock.shellHint": "外壳示意。不连接真机，不保存配置。",
      "mock.chip": "已记下：方向对，句子还不完整。"
    },
    en: {
      skip: "Skip to content",
      brand: "Exam cultivation",
      "aria.nav": "Pages",
      "aria.lang": "Language",
      "aria.style": "Style",
      "aria.layout": "Mock layout",
      "aria.screens": "Mock screens",
      "nav.home": "Home",
      "nav.product": "Product",
      "nav.gallery": "Styles",
      "nav.how": "How it works",
      "nav.contact": "Contact",
      "style.desk": "Practice desk",
      "style.studio": "Studio",
      "demo.toast": "Demo control. It does not submit and does not go online.",
      "foot.note": "Public showcase. No learner names, IDs, tokens, or conversations.",
      "foot.repo": "Repository",
      "title.home": "Exam cultivation · teaching-cultivator",
      "desc.home": "Agents that serve students: scheduled practice, a feedback loop, DingTalk notices, and two skins — Practice desk and Studio. No learner records.",
      "home.eyebrow": "Agents that serve students",
      "home.h1": "Scheduled practice, feedback, then the next item.",
      "home.lede": "teaching-cultivator serves students on a schedule: math, plus one or more other subjects you can configure. Communications in this showcase is only an example of that second subject. DingTalk delivers a short notice; answering and explanation happen on the practice desk. An optional Android shell, the Feedback Machine, runs the same loop. This site shows style and flow. Stems and numbers are placeholders.",
      "home.ctaGallery": "See both styles",
      "home.ctaProduct": "The product",
      "home.ctaContact": "Custom yaml",
      "home.f1t": "Scheduled practice",
      "home.f1b": "Morning and afternoon are subject pushes; the evening is review. Math and the other configured subjects come from a ready bank. The evening review is written when it is sent.",
      "home.f2t": "Feedback loop",
      "home.f2b": "After an answer, step feedback is written back onto the syllabus for the next pick. Every number on this site is drawn, not measured.",
      "home.f3t": "DingTalk delivery",
      "home.f3b": "The messenger gets a short notice and a deep link. Answering and explanation stay on the practice desk.",
      "home.f4t": "Optional shell",
      "home.f4b": "The Android Feedback Machine follows answer, feedback, next item. This showcase does not ship an installable package.",
      "home.privacy": "No real names, learner IDs, tokens, or conversation IDs. Every stem is a placeholder.",
      "home.demo": "Public practice entry (demo)",
      "home.demo2": "The link carries no token, and it does not replace your own access setup.",
      "title.product": "Product · Exam cultivation",
      "desc.product": "A cultivation agent for students: math, plus one or more configurable subjects. Communications in the demo is an example. DingTalk notices, the practice desk, and an optional Feedback Machine. No learner progress.",
      "prod.eyebrow": "Product",
      "prod.h1": "Math, plus other subjects you configure.",
      "prod.lede": "The agent decides what to practice today, writes an item when textbook evidence is present, calls the student in through DingTalk, then writes mastery back after grading. Besides math, one or more other subjects can be configured.",
      "prod.tracksT": "Subjects",
      "prod.mathT": "Math",
      "prod.mathB": "Day-to-day practice on a graduate math track.",
      "prod.commT": "Other subject (example: communications)",
      "prod.commB": "A second subject, and further ones, can be configured. This showcase uses a communications course as the example.",
      "prod.tracksNote": "This page does not show anyone’s progress. Communications in the mocks is only an example of a configurable subject.",
      "prod.surfT": "Three surfaces",
      "prod.s1t": "Practice desk",
      "prod.s1b": "A paper-colored page: stem card, grade bar, folded explanation, and “ask the tutor”.",
      "prod.s2t": "DingTalk",
      "prod.s2b": "A short notice and a link to the practice desk.",
      "prod.s3t": "Feedback Machine",
      "prod.s3b": "An optional Android shell on the same main path. This showcase does not ship an installable package.",
      "prod.gateT": "Evidence gate",
      "prod.gateB": "When textbook evidence is thin, authoring stops.",
      "prod.outT": "What this site leaves out",
      "prod.outB": "There is no learner list, gradebook, secret, or production endpoint here. The runtime can also assemble a biweekly paper; this site does not show one.",
      "prod.scopeT": "What is worth discussing",
      "prod.scopeB": "Configuration on the path that already exists: time slots, the subjects you teach, notice copy, and the Practice desk or Studio skin. Subjects are not limited to the communications example.",
      "title.gallery": "Styles · Practice desk and Studio",
      "desc.gallery": "CSS mock screens for Practice desk (warm paper) and Studio (cool ground, hard edges, crimson). Side by side or one at a time. Not learner screenshots.",
      "gal.eyebrow": "Styles",
      "gal.h1": "Warm paper, or a cool ground.",
      "gal.lede": "Practice desk (练习台) is warm paper: a cream ground, serif titles, a muted teal, a little paper grain. Studio (工作室) is a cool ground, hard edges, and crimson marks. These screens are CSS mockups, not learner screenshots.",
      "gal.help": "The header switch restyles the whole page. The two mock screens below keep their own colors. “Single” enlarges the skin you have selected.",
      "gal.pair": "Side by side",
      "gal.focus": "Single",
      "gal.queue": "Today",
      "gal.answer": "Answer",
      "gal.feedback": "Feedback",
      "gal.tutor": "Tutor",
      "gal.notice": "Notice",
      "gal.shell": "Shell",
      "title.how": "How it works · Exam cultivation",
      "desc.how": "From the schedule, the pick, and authoring, through a DingTalk notice, to grading and mastery write-back. Public flow only.",
      "how.eyebrow": "How it works",
      "how.h1": "From the schedule to write-back, with an evidence gate in between.",
      "how.lede": "This is the path a student can feel. Internal switches, secrets, and endpoints stay in the runtime.",
      "how.s1t": "Schedule",
      "how.s1b": "Morning and afternoon are subject pushes; the evening is review. Math and the other configured subjects are drawn from a ready bank. The evening review is written when it is sent.",
      "how.s2t": "Choose",
      "how.s2b": "Picks follow syllabus weight and mastery, and step aside from what was just practiced.",
      "how.s3t": "Author",
      "how.s3b": "An item is written when textbook evidence is there. When evidence is thin, authoring stops.",
      "how.s4t": "Deliver",
      "how.s4b": "DingTalk receives a short notice and a link to the practice desk. The answer is not piled into the chat.",
      "how.s5t": "Grade",
      "how.s5b": "Step feedback is given against the item.",
      "how.s6t": "Write back",
      "how.s6b": "Mastery is written back onto the syllabus so the next pick can use it.",
      "how.where": "The student taps on the practice desk or in the Feedback Machine. The notice only brings them there.",
      "how.secretT": "Configuration stays in the runtime",
      "how.secretB": "Tokens, conversations, and learner IDs stay in the runtime. They do not appear on this website.",
      "title.contact": "Contact · Exam cultivation",
      "desc.contact": "For the core yaml and customization, email longee142857@qq.com. DingTalk group custom service does not publish a group id here.",
      "con.eyebrow": "Contact",
      "con.h1": "Write for the core yaml and customization.",
      "con.lede": "Name the subjects you teach and the behavior you want changed. Subjects are not limited to the communications example. Custom work continues in a DingTalk group.",
      "con.mailT": "Email",
      "con.mailB": "Use the address to write. Put the subjects you teach in the subject line, one or more.",
      "con.groupT": "DingTalk group",
      "con.groupB": "Custom service happens in a DingTalk group. After you email what you need, you are invited in. This page does not publish a group id.",
      "con.yamlT": "Core yaml",
      "con.yamlB": "The core yaml and the cultivation setup already in use can be discussed by email. Do not attach tokens or learner IDs.",
      "con.noT": "Please do not send",
      "con.noB": "Tokens, learner IDs, conversation IDs, or real answer sheets.",
      "con.swatchDesk": "Warm paper · teal",
      "con.swatchStudio": "Cool ground · crimson",
      "mock.ribbon": "Demo",
      "mock.appName": "Daily practice",
      "mock.shellName": "Feedback Machine",
      "mock.today": "Three slots today",
      "mock.math": "Math",
      "mock.comm": "Communications",
      "mock.review": "Review",
      "mock.morning": "Morning",
      "mock.afternoon": "Afternoon",
      "mock.evening": "Evening",
      "mock.kpLimit": "Placeholder · limits",
      "mock.kpBase": "Placeholder · baseband",
      "mock.kpReview": "Placeholder · review",
      "mock.open": "Not answered",
      "mock.live": "Written at send time",
      "mock.hintQueue": "One math item, one communications item, one review. Communications is an example of a configurable subject. A missed slot can still be made up. Everything here is a placeholder.",
      "mock.tabPractice": "Practice",
      "mock.tabExam": "Paper",
      "mock.tabNotes": "Notes",
      "mock.tabTutor": "Tutor",
      "mock.stemEyebrow": "Placeholder stem · math",
      "mock.stemTitle": "Does the improper integral converge?",
      "mock.stemMath": "Placeholder: decide whether ∫ from 0 to ∞ of x²e^(−x) dx converges, and write the step you used to decide.",
      "mock.stemCommEyebrow": "Placeholder stem · communications (example)",
      "mock.stemComm": "Placeholder: in a band-limited channel, what happens when the symbol interval is shorter than the Nyquist interval? Answer in one sentence.",
      "mock.answerHint": "Write the steps here. Submit does not go online.",
      "mock.submit": "Submit",
      "mock.ask": "Ask the tutor",
      "mock.partial": "Partly right",
      "mock.step1": "The call on convergence points the right way.",
      "mock.step2": "The limit is only “goes to zero”; the comparison or integration-by-parts step is still missing.",
      "mock.mastery": "Placeholder mastery 0.42 → 0.48",
      "mock.masteryNote": "This number is drawn. It does not belong to anyone.",
      "mock.next": "Next item",
      "mock.you": "You",
      "mock.tutor": "Tutor",
      "mock.tutor1": "Placeholder dialogue. I can see the word “comparison” in the stem. There is no learner file.",
      "mock.user1": "I used a comparison test and did not name the function.",
      "mock.tutor2": "Name a function to compare with, and write the inequality’s direction.",
      "mock.askMore": "Ask more (demo)",
      "mock.noticeKicker": "DingTalk · notice mock",
      "mock.noticeTitle": "Today’s practice is ready",
      "mock.noticeBody": "One math item. Open the practice desk to answer. The explanation stays on the desk, not in this message.",
      "mock.openDesk": "Open the practice desk",
      "mock.noId": "No conversation id · no learner id",
      "mock.loop": "Answer → feedback → next item",
      "mock.shellHint": "Shell mockup. It does not connect to a device and does not store settings.",
      "mock.chip": "Noted: the direction is right; the sentence is still incomplete."
    }
  };

  function lang() {
    return document.documentElement.lang === "en" ? "en" : "zh";
  }

  function pack() {
    return STR[lang()] || STR.zh;
  }

  function t(key) {
    var table = pack();
    if (table[key] != null) return table[key];
    if (STR.zh[key] != null) return STR.zh[key];
    return key;
  }

  function apply() {
    var table = pack();
    var nodes = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var key = el.getAttribute("data-i18n");
      if (table[key] == null) continue;
      el.textContent = table[key];
    }
    var ariaNodes = document.querySelectorAll("[data-i18n-aria]");
    for (var j = 0; j < ariaNodes.length; j++) {
      var ariaEl = ariaNodes[j];
      var ariaKey = ariaEl.getAttribute("data-i18n-aria");
      if (table[ariaKey] != null) ariaEl.setAttribute("aria-label", table[ariaKey]);
    }
    var titleKey = document.body && document.body.getAttribute("data-title");
    if (titleKey && table[titleKey]) document.title = table[titleKey];
    var desc = document.querySelector('meta[name="description"]');
    var descKey = document.body && document.body.getAttribute("data-desc");
    if (desc && descKey && table[descKey]) desc.setAttribute("content", table[descKey]);
    var current = lang();
    var langButtons = document.querySelectorAll("[data-lang]");
    for (var a = 0; a < langButtons.length; a++) {
      var onLang = langButtons[a].getAttribute("data-lang") === current;
      langButtons[a].setAttribute("aria-pressed", onLang ? "true" : "false");
      langButtons[a].classList.toggle("is-on", onLang);
    }
    var style = document.documentElement.getAttribute("data-style") || "desk";
    var styleButtons = document.querySelectorAll("[data-set-style]");
    for (var b = 0; b < styleButtons.length; b++) {
      var onStyle = styleButtons[b].getAttribute("data-set-style") === style;
      styleButtons[b].setAttribute("aria-pressed", onStyle ? "true" : "false");
      styleButtons[b].classList.toggle("is-on", onStyle);
    }
    var page = document.body && document.body.getAttribute("data-page");
    var nav = document.querySelectorAll("[data-nav]");
    for (var c = 0; c < nav.length; c++) {
      if (nav[c].getAttribute("data-nav") === page) nav[c].setAttribute("aria-current", "page");
      else nav[c].removeAttribute("aria-current");
    }
    var theme = document.querySelector('meta[name="theme-color"]');
    if (theme) theme.setAttribute("content", style === "studio" ? "#141A22" : "#F4EDE0");
    document.dispatchEvent(new CustomEvent("tc:lang"));
  }

  function setLang(next) {
    if (next !== "en" && next !== "zh") return;
    try { localStorage.setItem("tc-lang", next); } catch (err) { /* ignore */ }
    document.documentElement.lang = next === "en" ? "en" : "zh-CN";
    apply();
  }

  function setStyle(next) {
    if (next !== "studio" && next !== "desk") return;
    try { localStorage.setItem("tc-style", next); } catch (err) { /* ignore */ }
    document.documentElement.setAttribute("data-style", next);
    apply();
  }

  function onClick(ev) {
    var langBtn = ev.target.closest("[data-lang]");
    if (langBtn) {
      setLang(langBtn.getAttribute("data-lang"));
      return;
    }
    var styleBtn = ev.target.closest("[data-set-style]");
    if (styleBtn) {
      setStyle(styleBtn.getAttribute("data-set-style"));
      return;
    }
    var demo = ev.target.closest("[data-demo]");
    if (demo) {
      var toast = document.getElementById("demo-toast");
      if (toast) {
        toast.hidden = false;
        toast.textContent = t("demo.toast");
      }
    }
  }

  function boot() {
    if (!document.body) return;
    apply();
    document.body.addEventListener("click", onClick);
  }

  if (typeof window !== "undefined") {
    window.TC = { t: t, setLang: setLang, setStyle: setStyle, apply: apply, STR: STR };
  }
  if (typeof document === "undefined") return;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
