<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="en_US">
<context>
    <name>FloatingButton</name>
    <message>
        <location filename="../ui/floating_button.py" line="65"/>
        <source>Зажмите для записи</source>
        <translation>Hold to record</translation>
    </message>
</context>
<context>
    <name>Indicator</name>
    <message>
        <location filename="../ui/indicator.py" line="57"/>
        <source>Запись</source>
        <translation>Recording</translation>
    </message>
    <message>
        <location filename="../ui/indicator.py" line="64"/>
        <source>Распознавание…</source>
        <translation>Transcribing…</translation>
    </message>
    <message>
        <location filename="../ui/indicator.py" line="69"/>
        <source>Обработка…</source>
        <translation>Polishing…</translation>
    </message>
</context>
<context>
    <name>SettingsWindow</name>
    <message>
        <location filename="../ui/settings.py" line="84"/>
        <source>Söyle — настройки</source>
        <translation>Söyle — Settings</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="91"/>
        <source>Хоткей</source>
        <translation>Hotkey</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="92"/>
        <source>Аудио</source>
        <translation>Audio</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="95"/>
        <source>Словарь</source>
        <translation>Dictionary</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="100"/>
        <source>Внешний вид</source>
        <translation>Appearance</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="101"/>
        <source>О программе</source>
        <translation>About</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="112"/>
        <source>Сохранить</source>
        <translation>Save</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="115"/>
        <source>Закрыть</source>
        <translation>Close</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="144"/>
        <source>Записать…</source>
        <translation>Capture…</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="147"/>
        <source>Нажать клавишу и распознать её автоматически</source>
        <translation>Press a key and detect it automatically</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="154"/>
        <source>Клавиша:</source>
        <translation>Key:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="159"/>
        <location filename="../ui/settings.py" line="321"/>
        <source>Режим:</source>
        <translation>Mode:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="163"/>
        <source>Debounce (мс):</source>
        <translation>Debounce (ms):</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="182"/>
        <source>Устройство:</source>
        <translation>Device:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="186"/>
        <source>Макс. запись (сек):</source>
        <translation>Max. recording (sec):</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="189"/>
        <source>Обрезать тишину в начале и конце записи</source>
        <translation>Trim silence at the start and end of recording</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="194"/>
        <source>Удаляет тихие фреймы по краям записи. Помогает когда коллеги говорят рядом — их голос будет ниже порога и обрежется.</source>
        <translation>Removes silent frames from the edges of the recording. Helps when colleagues are talking nearby — their voice will be below the threshold and will be trimmed.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="212"/>
        <source>Порог RMS-энергии для определения тишины. Ниже = пропускает тихую/удалённую речь. Выше = только громкая близкая речь.</source>
        <translation>RMS energy threshold for silence detection. Lower = passes quiet/distant speech. Higher = only loud close-range speech.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="217"/>
        <source>Порог тишины (RMS):</source>
        <translation>Silence threshold (RMS):</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="238"/>
        <location filename="../ui/settings.py" line="334"/>
        <source>Модель:</source>
        <translation>Model:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="242"/>
        <source>Device:</source>
        <translation>Device:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="246"/>
        <source>Compute type:</source>
        <translation>Compute type:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="257"/>
        <source>Авто (определять автоматически)</source>
        <translation>Auto (detect automatically)</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="263"/>
        <source>Язык:</source>
        <translation>Language:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="273"/>
        <source>Auto-detect рекомендуется для смешанной RU+EN речи. Принудительный выбор ru/en даёт лучше recognition строго-моноязычной диктовки, но ломает code-switching. Казахский пока ненадёжен — fix в работе (dual-model).</source>
        <translation>Auto-detect is recommended for mixed RU+EN speech. Forcing ru/en gives better recognition for strictly monolingual dictation, but breaks code-switching. Kazakh is not yet reliable — a fix is in progress (dual-model).</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="287"/>
        <source>Включить постобработку LLM</source>
        <translation>Enable LLM post-processing</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="293"/>
        <source>Polish — чистка, пунктуация, без переформулирования</source>
        <translation>Polish — cleanup, punctuation, no rephrasing</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="297"/>
        <source>Rewrite — активная переформулировка в связный текст</source>
        <translation>Rewrite — active rephrasing into coherent text</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="302"/>
        <source>AI Prompt — превратить речь в инструкцию для Claude/ChatGPT/Gemini</source>
        <translation>AI Prompt — turn speech into a prompt for Claude/ChatGPT/Gemini</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="308"/>
        <source>Plain Text — текст для документа (Word, email, мессенджер)</source>
        <translation>Plain Text — text for a document (Word, email, messenger)</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="314"/>
        <source>Task — структурированная задача (Задача / Департамент / Приоритет / Описание)</source>
        <translation>Task — structured task (Task / Department / Priority / Description)</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="338"/>
        <source>Таймаут (сек):</source>
        <translation>Timeout (sec):</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="348"/>
        <source>sk-or-v1-…</source>
        <translation>sk-or-v1-…</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="350"/>
        <location filename="../ui/settings.py" line="655"/>
        <source>Показать</source>
        <translation>Show</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="354"/>
        <source>Временно сделать ключ видимым</source>
        <translation>Temporarily make the key visible</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="358"/>
        <source>Удалить</source>
        <translation>Delete</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="361"/>
        <source>Стереть сохранённый ключ из Windows Credential Manager</source>
        <translation>Clear the saved key from Windows Credential Manager</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="369"/>
        <source>OpenRouter API key:</source>
        <translation>OpenRouter API key:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="392"/>
        <source>Синхронизация словаря, настроек и истории usage через Google Drive.
Запускается ежедневно при старте Söyle; изменения настроек уходят
сразу же (с задержкой ~8 секунд). Поля привязанные к железу
(микрофон, модель Whisper, тема) остаются локальными.</source>
        <translation>Sync of dictionary, settings, and usage history via Google Drive.
Runs daily on Söyle startup; settings changes are uploaded
immediately (with ~8-second delay). Hardware-specific fields
(microphone, Whisper model, theme) remain local.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="415"/>
        <source>Подключить Google Drive</source>
        <translation>Connect Google Drive</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="419"/>
        <source>Синхронизировать сейчас</source>
        <translation>Sync now</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="422"/>
        <source>Отключить</source>
        <translation>Disconnect</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="436"/>
        <source>✓ Подключено к Google Drive</source>
        <translation>✓ Connected to Google Drive</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="437"/>
        <source>Не подключено</source>
        <translation>Not connected</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="444"/>
        <source>Последняя синхронизация: никогда</source>
        <translation>Last sync: never</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="446"/>
        <source>Последняя синхронизация: {time}</source>
        <translation>Last sync: {time}</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="461"/>
        <location filename="../ui/settings.py" line="502"/>
        <location filename="../ui/settings.py" line="560"/>
        <location filename="../ui/settings.py" line="621"/>
        <location filename="../ui/settings.py" line="626"/>
        <source>Söyle — Cloud Sync</source>
        <translation>Söyle — Cloud Sync</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="463"/>
        <source>Открыл браузер для авторизации в Google. Подтвердите и вернитесь.</source>
        <translation>Opened browser for Google authorization. Confirm and return.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="503"/>
        <source>Подключено. Backup начнётся автоматически.</source>
        <translation>Connected. Backup will start automatically.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="510"/>
        <source>Söyle — найден backup</source>
        <translation>Söyle — backup found</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="513"/>
        <source>В Google Drive найден backup словаря: {count} терминов (обновлён {date}).

Объединить с локальным словарём сейчас?</source>
        <translation>A dictionary backup was found in Google Drive: {count} terms (updated {date}).

Merge with the local dictionary now?</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="536"/>
        <source>Söyle — настройки с другого устройства</source>
        <translation>Söyle — settings from another device</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="538"/>
        <source>Найдены настройки с другого устройства. Применить?
(Локальные значения для микрофона, модели Whisper и темы
оформления останутся как есть.)</source>
        <translation>Settings from another device found. Apply?
(Local values for microphone, Whisper model, and theme
will remain unchanged.)</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="562"/>
        <source>Настройки с другого устройства применены. Открой Settings заново, чтобы увидеть значения.</source>
        <translation>Settings from another device applied. Reopen Settings to see the updated values.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="597"/>
        <location filename="../ui/settings.py" line="665"/>
        <location filename="../ui/settings.py" line="899"/>
        <source>Söyle</source>
        <translation>Söyle</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="598"/>
        <source>Sync OK. Локально +{local}, в Drive +{remote}.</source>
        <translation>Sync OK. Locally +{local}, in Drive +{remote}.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="622"/>
        <source>Отключено от Google Drive.</source>
        <translation>Disconnected from Google Drive.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="655"/>
        <source>Скрыть</source>
        <translation>Hide</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="667"/>
        <source>Удалить сохранённый API-ключ из Windows Credential Manager?
Постобработка вернётся к выводу сырых транскриптов, пока не задан новый ключ.</source>
        <translation>Delete the saved API key from Windows Credential Manager?
Post-processing will revert to raw transcripts until a new key is provided.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="688"/>
        <source>✓ Ключ сохранён: {head}…{tail}  ·  хранится в Windows Credential Manager</source>
        <translation>✓ Key saved: {head}…{tail}  ·  stored in Windows Credential Manager</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="696"/>
        <source>✗ Ключ не задан — постобработка работает в fallback-режиме</source>
        <translation>✗ Key not set — post-processing running in fallback mode</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="707"/>
        <source>Тема:</source>
        <translation>Theme:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="710"/>
        <source>Системный</source>
        <translation>System</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="716"/>
        <source>Язык интерфейса:</source>
        <translation>Interface language:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="721"/>
        <source>Звуковые сигналы</source>
        <translation>Sound effects</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="725"/>
        <source>Показать floating-кнопку для диктовки мышью</source>
        <translation>Show floating button for mouse dictation</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="730"/>
        <source>Круглая иконка микрофона в правом нижнем углу. Зажми и говори — альтернатива Right Alt.</source>
        <translation>Round microphone icon in the bottom-right corner. Hold and speak — an alternative to Right Alt.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="735"/>
        <source>Запуск при старте Windows</source>
        <translation>Launch at Windows startup</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="740"/>
        <source>Буфер обмена (быстрее, совместимо)</source>
        <translation>Clipboard (faster, compatible)</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="743"/>
        <source>Эмуляция клавиш (не трогает буфер)</source>
        <translation>Key emulation (does not touch clipboard)</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="747"/>
        <source>Метод вставки:</source>
        <translation>Paste method:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="756"/>
        <source>Предупреждение в трее при превышении. 0 = выключено.</source>
        <translation>Tray warning when exceeded. 0 = disabled.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="758"/>
        <source>Лимит в месяц:</source>
        <translation>Monthly limit:</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="767"/>
        <source>Термины из словаря подсказываются Whisper при распознавании и LLM при полировке (имена, бренды, техническая лексика).</source>
        <translation>Dictionary terms are suggested to Whisper during recognition and to the LLM during polishing (names, brands, technical vocabulary).</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="779"/>
        <source>Söyle, OpenRouter, Nurgisa ...</source>
        <translation>Söyle, OpenRouter, Nurgisa ...</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="781"/>
        <source>Добавить</source>
        <translation>Add</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="788"/>
        <source>Удалить выбранные</source>
        <translation>Delete selected</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="791"/>
        <source>Очистить всё</source>
        <translation>Clear all</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="829"/>
        <source>Локальная диктовка через Whisper + OpenRouter для постобработки.</source>
        <translation>Local dictation via Whisper + OpenRouter for post-processing.</translation>
    </message>
    <message>
        <location filename="../ui/settings.py" line="900"/>
        <source>Язык интерфейса изменится после перезапуска.</source>
        <translation>Interface language will change after restart.</translation>
    </message>
</context>
<context>
    <name>SoyleApp</name>
    <message>
        <location filename="../app.py" line="242"/>
        <location filename="../app.py" line="322"/>
        <location filename="../app.py" line="339"/>
        <location filename="../app.py" line="456"/>
        <location filename="../app.py" line="480"/>
        <location filename="../app.py" line="485"/>
        <location filename="../app.py" line="488"/>
        <location filename="../app.py" line="493"/>
        <location filename="../app.py" line="512"/>
        <location filename="../app.py" line="603"/>
        <location filename="../app.py" line="650"/>
        <location filename="../app.py" line="656"/>
        <location filename="../app.py" line="669"/>
        <location filename="../app.py" line="694"/>
        <source>Söyle</source>
        <translation>Söyle</translation>
    </message>
    <message>
        <location filename="../app.py" line="242"/>
        <source>Не удалось зарегистрировать хоткей. Откройте настройки.</source>
        <translation>Could not register the hotkey. Open settings.</translation>
    </message>
    <message>
        <location filename="../app.py" line="322"/>
        <source>Режим LLM: {label}</source>
        <translation>LLM mode: {label}</translation>
    </message>
    <message>
        <location filename="../app.py" line="339"/>
        <source>Микрофон: {exc}</source>
        <translation>Microphone: {exc}</translation>
    </message>
    <message>
        <location filename="../app.py" line="370"/>
        <source>Слишком коротко</source>
        <translation>Too short</translation>
    </message>
    <message>
        <location filename="../app.py" line="398"/>
        <source>Отменено</source>
        <translation>Cancelled</translation>
    </message>
    <message>
        <location filename="../app.py" line="421"/>
        <source>Ошибка распознавания</source>
        <translation>Recognition error</translation>
    </message>
    <message>
        <location filename="../app.py" line="440"/>
        <source>Ничего не распознано</source>
        <translation>Nothing recognised</translation>
    </message>
    <message>
        <location filename="../app.py" line="457"/>
        <source>Терминал: текст в буфере — вставьте вручную (Ctrl+V)</source>
        <translation>Terminal: text is in the clipboard — paste manually (Ctrl+V)</translation>
    </message>
    <message>
        <location filename="../app.py" line="481"/>
        <source>Проверьте API-ключ OpenRouter в настройках</source>
        <translation>Check your OpenRouter API key in settings</translation>
    </message>
    <message>
        <location filename="../app.py" line="485"/>
        <source>OpenRouter: превышен лимит, попробуйте позже</source>
        <translation>OpenRouter: rate limit exceeded, try again later</translation>
    </message>
    <message>
        <location filename="../app.py" line="488"/>
        <source>Сеть недоступна — вставлен сырой текст</source>
        <translation>Network unavailable — raw text inserted</translation>
    </message>
    <message>
        <location filename="../app.py" line="493"/>
        <source>LLM недоступна — вставлен сырой текст</source>
        <translation>LLM unavailable — raw text inserted</translation>
    </message>
    <message>
        <location filename="../app.py" line="513"/>
        <source>Месячный лимит превышен: ${current} из ${limit}</source>
        <translation>Monthly limit exceeded: ${current} of ${limit}</translation>
    </message>
    <message>
        <location filename="../app.py" line="549"/>
        <source>Добро пожаловать в Söyle</source>
        <translation>Welcome to Söyle</translation>
    </message>
    <message>
        <location filename="../app.py" line="551"/>
        <source>Вставьте OpenRouter API-ключ, чтобы включить полировку. Без ключа можно работать — получите сырую транскрипцию.</source>
        <translation>Paste your OpenRouter API key to enable polishing. You can work without a key — you will get raw transcription.</translation>
    </message>
    <message>
        <location filename="../app.py" line="564"/>
        <source>Söyle — Cloud Sync</source>
        <translation>Söyle — Cloud Sync</translation>
    </message>
    <message>
        <location filename="../app.py" line="566"/>
        <source>Подключите Google Drive в Settings → Cloud Sync, чтобы синхронизировать словарь между устройствами и иметь backup.</source>
        <translation>Connect Google Drive in Settings → Cloud Sync to sync your dictionary across devices and keep a backup.</translation>
    </message>
    <message>
        <location filename="../app.py" line="603"/>
        <source>Настройки сохранены</source>
        <translation>Settings saved</translation>
    </message>
    <message>
        <location filename="../app.py" line="651"/>
        <source>Google Drive отключён. Подключите заново в Settings.</source>
        <translation>Google Drive disconnected. Reconnect in Settings.</translation>
    </message>
    <message>
        <location filename="../app.py" line="657"/>
        <source>Google Drive переполнен. Освободите место или disconnect.</source>
        <translation>Google Drive is full. Free up space or disconnect.</translation>
    </message>
    <message>
        <location filename="../app.py" line="662"/>
        <source>Söyle — Google заблокировал приложение</source>
        <translation>Söyle — Google has suspended the app</translation>
    </message>
    <message>
        <location filename="../app.py" line="663"/>
        <source>Контакт: andasbek.nurgysa@gmail.com</source>
        <translation>Contact: andasbek.nurgysa@gmail.com</translation>
    </message>
    <message>
        <location filename="../app.py" line="670"/>
        <source>Sync: добавлено {n} терминов.</source>
        <translation>Sync: {n} term(s) added.</translation>
    </message>
    <message>
        <location filename="../app.py" line="694"/>
        <source>Логов пока нет</source>
        <translation>No logs yet</translation>
    </message>
    <message>
        <location filename="../app.py" line="793"/>
        <source>Söyle — непредвиденная ошибка</source>
        <translation>Söyle — unexpected error</translation>
    </message>
    <message>
        <location filename="../app.py" line="798"/>
        <source>Приложите этот файл к багрепорту.</source>
        <translation>Attach this file to the bug report.</translation>
    </message>
    <message>
        <location filename="../app.py" line="803"/>
        <source>Лог сохранён:
{path}

</source>
        <translation>Log saved:
{path}

</translation>
    </message>
</context>
<context>
    <name>TrayIcon</name>
    <message>
        <location filename="../ui/tray.py" line="37"/>
        <source>Режим</source>
        <translation>Mode</translation>
    </message>
    <message>
        <location filename="../ui/tray.py" line="55"/>
        <source>Расход: $0.0000 (0)</source>
        <translation>Usage: $0.0000 (0)</translation>
    </message>
    <message>
        <location filename="../ui/tray.py" line="61"/>
        <source>Настройки…</source>
        <translation>Settings…</translation>
    </message>
    <message>
        <location filename="../ui/tray.py" line="63"/>
        <source>Показать логи</source>
        <translation>Show logs</translation>
    </message>
    <message>
        <location filename="../ui/tray.py" line="65"/>
        <source>Выход</source>
        <translation>Quit</translation>
    </message>
    <message>
        <location filename="../ui/tray.py" line="89"/>
        <source>Söyle — режим {label}</source>
        <translation>Söyle — {label} mode</translation>
    </message>
</context>
</TS>
