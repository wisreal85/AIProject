using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace KidsPlayGuide
{
    /// <summary>
    /// 앱 진입점. 어떤 씬에서든 플레이를 누르면 스스로 생성되어 화면 전체를 코드로 그린다.
    /// 화면 흐름: 아이 등록 → 홈(오늘의 놀이 3개) → 놀이 상세 → 기록 / 수면 / 부모.
    /// </summary>
    public class App : MonoBehaviour
    {
        enum Page { Register, Home, AllPlays, Detail, Records, Sleep, Parent }

        const float HeaderHeight = 140f;
        const float TabHeight = 150f;
        const float ColumnWidth = 1080f;

        /// <summary>후원 페이지 주소. 비워 두면 "준비 중"으로 안내한다.</summary>
        const string SupportUrl = "";

        static readonly Color NightCard = new Color32(0x3A, 0x40, 0x66, 0xFF);
        static readonly string[] ReactionLabels = { "", "좋아했어요", "보통이었어요", "관심 없었어요" };
        static readonly int[] TimerOptions = { 15, 30, 60, 0 };

        Page _page;
        Page _detailBack = Page.Home;
        Play _play;

        Canvas _canvas;
        CanvasScaler _scaler;
        Image _background;
        RectTransform _column;
        RectTransform _screen;
        SleepAudioPlayer _audio;
        Text _sleepStatus;
        Rect _lastSafeArea;
        int _lastWidth, _lastHeight;
        bool _legacyInput = true;

        // 화면별 임시 상태
        int _regYear, _regMonth, _regDay;
        int _reaction;
        bool _confirmReset;
        string _notice = "";

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Boot()
        {
            if (FindAnyObjectByType<App>() != null) return;
            var go = new GameObject("KidsPlayGuideApp");
            DontDestroyOnLoad(go);
            go.AddComponent<App>();
        }

        void Awake()
        {
            Application.targetFrameRate = 60;
            Application.runInBackground = true;
            AppState.Load();

            EnsureCameraAndInput();
            BuildCanvas();

            _audio = gameObject.AddComponent<SleepAudioPlayer>();
            _audio.SetVolume(AppState.Data.volume);

            _page = AppState.Data.hasChild ? Page.Home : Page.Register;
            PrepareRegister();
            Render();
        }

        void EnsureCameraAndInput()
        {
            var cam = Camera.main;
            if (cam == null) cam = FindAnyObjectByType<Camera>();
            if (cam == null)
            {
                var camGo = new GameObject("Main Camera");
                camGo.tag = "MainCamera";
                camGo.transform.SetParent(transform, false);
                cam = camGo.AddComponent<Camera>();
            }
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = UI.Bg;

            if (FindAnyObjectByType<AudioListener>() == null) cam.gameObject.AddComponent<AudioListener>();

            if (FindAnyObjectByType<EventSystem>() == null)
            {
                var es = new GameObject("EventSystem");
                es.transform.SetParent(transform, false);
                es.AddComponent<EventSystem>();
                es.AddComponent<StandaloneInputModule>();
            }
        }

        void BuildCanvas()
        {
            var go = new GameObject("Canvas", typeof(RectTransform));
            go.layer = 5;
            go.transform.SetParent(transform, false);
            _canvas = go.AddComponent<Canvas>();
            _canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            _scaler = go.AddComponent<CanvasScaler>();
            _scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            _scaler.referenceResolution = new Vector2(ColumnWidth, 1920f);
            _scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
            go.AddComponent<GraphicRaycaster>();

            var bg = UI.Node("Background", go.transform);
            UI.Stretch(bg);
            _background = UI.Fill(bg, UI.Bg, false);

            // 세로 화면 폭(1080)으로 고정한 가운데 기둥. 가로 화면·태블릿에서도 같은 배치를 유지한다.
            _column = UI.Node("Column", go.transform);
            _column.anchorMin = new Vector2(0.5f, 0f);
            _column.anchorMax = new Vector2(0.5f, 1f);
            ApplyScreenShape();
        }

        void ApplyScreenShape()
        {
            _lastWidth = Screen.width;
            _lastHeight = Screen.height;
            _lastSafeArea = Screen.safeArea;

            bool landscape = Screen.width * 1920f > Screen.height * ColumnWidth;
            _scaler.matchWidthOrHeight = landscape ? 1f : 0f;
            float scale = landscape ? Screen.height / 1920f : Screen.width / ColumnWidth;
            if (scale <= 0f) scale = 1f;

            float bottom = _lastSafeArea.yMin / scale;
            float top = (Screen.height - _lastSafeArea.yMax) / scale;
            _column.offsetMin = new Vector2(-ColumnWidth / 2f, Mathf.Max(0f, bottom));
            _column.offsetMax = new Vector2(ColumnWidth / 2f, -Mathf.Max(0f, top));
        }

        void Update()
        {
            if (Screen.width != _lastWidth || Screen.height != _lastHeight || Screen.safeArea != _lastSafeArea)
                ApplyScreenShape();

            if (_legacyInput)
            {
                try
                {
                    if (Input.GetKeyDown(KeyCode.Escape)) Back();
                }
                catch (InvalidOperationException)
                {
                    _legacyInput = false; // 새 Input System 만 켜진 프로젝트
                }
            }

            if (_sleepStatus != null) _sleepStatus.text = SleepStatusText();
        }

        void OnApplicationPause(bool paused)
        {
            if (paused) AppState.Save();
        }

        // ───────── 이동 ─────────

        void Go(Page page)
        {
            _page = page;
            _confirmReset = false;
            _notice = "";
            Render();
        }

        void OpenDetail(Play play)
        {
            _detailBack = _page;
            _play = play;
            var today = AppState.FindRecord(play.id, AgeUtil.DateKey(DateTime.Now));
            _reaction = today != null ? today.reaction : 0;
            Go(Page.Detail);
        }

        void Back()
        {
            switch (_page)
            {
                case Page.Detail: Go(_detailBack); break;
                case Page.AllPlays: Go(Page.Home); break;
                case Page.Register:
                    if (AppState.Data.hasChild) Go(Page.Parent);
                    break;
                case Page.Home: break;
                default: Go(Page.Home); break;
            }
        }

        int ChildMonths()
        {
            return AgeUtil.MonthsOld(AppState.Data.child.BirthDate, DateTime.Now.Date);
        }

        // ───────── 공통 틀 ─────────

        void Render()
        {
            if (_screen != null)
            {
                _screen.gameObject.SetActive(false);
                Destroy(_screen.gameObject);
            }
            _sleepStatus = null;

            bool night = _page == Page.Sleep;
            _background.color = night ? UI.Night : UI.Bg;
            if (Camera.main != null) Camera.main.backgroundColor = _background.color;

            _screen = UI.Node("Screen", _column);
            UI.Stretch(_screen);

            bool showTabs = _page != Page.Register && _page != Page.Detail && _page != Page.AllPlays;
            bool showBack = _page == Page.Detail || _page == Page.AllPlays ||
                            (_page == Page.Register && AppState.Data.hasChild);

            // 머리글
            var header = UI.Node("Header", _screen);
            header.anchorMin = new Vector2(0, 1);
            header.anchorMax = new Vector2(1, 1);
            header.pivot = new Vector2(0.5f, 1);
            header.sizeDelta = new Vector2(0, HeaderHeight);
            var title = UI.Label(header, TitleFor(_page), 46, night ? Color.white : UI.Ink, FontStyle.Bold, TextAnchor.MiddleCenter);
            UI.Stretch(title.rectTransform, 180, 0, 180, 0);
            if (showBack)
            {
                var back = UI.Btn(header, "뒤로", Back, UI.Soft, UI.Ink, 90, 34);
                var brt = (RectTransform)back.transform;
                brt.anchorMin = new Vector2(0, 0.5f);
                brt.anchorMax = new Vector2(0, 0.5f);
                brt.pivot = new Vector2(0, 0.5f);
                brt.anchoredPosition = new Vector2(32, 0);
                brt.sizeDelta = new Vector2(170, 90);
            }

            // 본문
            var body = UI.Node("Body", _screen);
            UI.Stretch(body, 0, HeaderHeight, 0, showTabs ? TabHeight : 0);
            switch (_page)
            {
                case Page.Register: BuildRegister(body); break;
                case Page.Home: BuildHome(body); break;
                case Page.AllPlays: BuildAllPlays(body); break;
                case Page.Detail: BuildDetail(body); break;
                case Page.Records: BuildRecords(body); break;
                case Page.Sleep: BuildSleep(body); break;
                case Page.Parent: BuildParent(body); break;
            }

            if (showTabs) BuildTabs(night);
        }

        string TitleFor(Page page)
        {
            switch (page)
            {
                case Page.Register: return AppState.Data.hasChild ? "아이 정보 수정" : "오늘의 놀이";
                case Page.Home: return "오늘의 놀이";
                case Page.AllPlays: return "이 월령의 놀이";
                case Page.Detail: return "놀이 방법";
                case Page.Records: return "놀이 기록";
                case Page.Sleep: return "수면 소리";
                default: return "부모 화면";
            }
        }

        void BuildTabs(bool night)
        {
            var bar = UI.HBox(_screen, 0, "Tabs");
            bar.anchorMin = new Vector2(0, 0);
            bar.anchorMax = new Vector2(1, 0);
            bar.pivot = new Vector2(0.5f, 0);
            bar.sizeDelta = new Vector2(0, TabHeight);
            var barColor = night ? NightCard : UI.Card;
            UI.Fill(bar, barColor, false);
            var group = bar.GetComponent<HorizontalLayoutGroup>();
            group.childForceExpandWidth = true;
            group.childForceExpandHeight = true;

            Tab(bar, "홈", Page.Home, barColor, night);
            Tab(bar, "기록", Page.Records, barColor, night);
            Tab(bar, "수면", Page.Sleep, barColor, night);
            Tab(bar, "부모", Page.Parent, barColor, night);
        }

        void Tab(Transform bar, string label, Page page, Color barColor, bool night)
        {
            bool active = _page == page;
            Color idle = night ? new Color(1, 1, 1, 0.6f) : UI.Sub;
            var b = UI.Btn(bar, label, () => Go(page), barColor, active ? UI.Primary : idle, TabHeight, active ? 42 : 38);
            b.GetComponent<Image>().sprite = null;
            UI.Size(b, -1, -1, 1);
        }

        // ───────── 아이 등록 ─────────

        void PrepareRegister()
        {
            if (AppState.Data.hasChild)
            {
                var c = AppState.Data.child;
                _regYear = c.birthYear; _regMonth = c.birthMonth; _regDay = c.birthDay;
            }
            else
            {
                var d = DateTime.Now.Date.AddMonths(-18);
                _regYear = d.Year; _regMonth = d.Month; _regDay = d.Day;
            }
        }

        void BuildRegister(RectTransform body)
        {
            RectTransform content;
            UI.Scroll(body, out content);
            bool editing = AppState.Data.hasChild;

            if (!editing)
            {
                UI.Label(content, "아이 정보를 알려 주세요", 56, UI.Ink, FontStyle.Bold);
                UI.Label(content, "월령에 맞는 놀이를 매일 3개씩 골라 드려요.\n정보는 이 기기에만 저장되고 어디로도 보내지 않아요.", 36, UI.Sub);
            }

            var nameCard = UI.CardBox(content);
            UI.Label(nameCard, "이름 (애칭도 좋아요)", 34, UI.Sub);
            var nameInput = UI.Input(nameCard, "예: 콩이", AppState.Data.child.name, false, 12);

            var birthCard = UI.CardBox(content, null, 20);
            UI.Label(birthCard, "생년월일", 34, UI.Sub);
            var ageLabel = UI.Label(birthCard, "", 40, UI.Primary, FontStyle.Bold);
            Text yearText = null, monthText = null, dayText = null;

            Action refresh = () =>
            {
                int thisYear = DateTime.Now.Year;
                _regYear = Mathf.Clamp(_regYear, thisYear - 7, thisYear);
                if (_regMonth < 1) _regMonth = 12;
                if (_regMonth > 12) _regMonth = 1;
                int days = DateTime.DaysInMonth(_regYear, _regMonth);
                if (_regDay < 1) _regDay = days;
                if (_regDay > days) _regDay = 1;

                yearText.text = _regYear + "년";
                monthText.text = _regMonth + "월";
                dayText.text = _regDay + "일";

                var birth = new DateTime(_regYear, _regMonth, _regDay);
                ageLabel.text = birth > DateTime.Now.Date
                    ? "아직 오지 않은 날짜예요"
                    : "지금 " + AgeUtil.AgeLabel(AgeUtil.MonthsOld(birth, DateTime.Now.Date));
            };

            yearText = Stepper(birthCard, d => { _regYear += d; refresh(); });
            monthText = Stepper(birthCard, d => { _regMonth += d; refresh(); });
            dayText = Stepper(birthCard, d => { _regDay += d; refresh(); });
            refresh();

            UI.Btn(content, editing ? "저장하기" : "시작하기", () =>
            {
                var birth = new DateTime(_regYear, _regMonth, _regDay);
                if (birth > DateTime.Now.Date) return;
                var c = AppState.Data.child;
                string n = nameInput.text == null ? "" : nameInput.text.Trim();
                c.name = n.Length > 0 ? n : "우리 아이";
                c.birthYear = _regYear; c.birthMonth = _regMonth; c.birthDay = _regDay;
                AppState.Data.hasChild = true;
                AppState.Save();
                Go(editing ? Page.Parent : Page.Home);
            });
        }

        Text Stepper(Transform parent, Action<int> onStep)
        {
            var row = UI.HBox(parent, 16);
            UI.Size(UI.Btn(row, "-", () => onStep(-1), UI.Soft, UI.Ink, 110, 52), 150);
            var value = UI.Label(row, "", 46, UI.Ink, FontStyle.Bold, TextAnchor.MiddleCenter);
            UI.Size(value, -1, -1, 1);
            UI.Size(UI.Btn(row, "+", () => onStep(1), UI.Soft, UI.Ink, 110, 52), 150);
            return value;
        }

        // ───────── 홈 ─────────

        void BuildHome(RectTransform body)
        {
            RectTransform content;
            UI.Scroll(body, out content);
            var today = DateTime.Now.Date;
            int months = ChildMonths();
            var child = AppState.Data.child;

            var hello = UI.CardBox(content, UI.Primary);
            UI.Label(hello, child.name + ", 오늘은 뭐 하고 놀까?", 50, Color.white, FontStyle.Bold);
            UI.Label(hello, string.Format("{0}년 {1}월 {2}일 · {3}", today.Year, today.Month, today.Day, AgeUtil.AgeLabel(months)),
                34, new Color(1, 1, 1, 0.9f));

            if (!PlayRepository.IsAgeCovered(months))
            {
                var note = UI.CardBox(content, UI.Soft);
                UI.Label(note, "지금 놀이는 12~36개월에 맞춰져 있어요. 가장 가까운 월령의 놀이를 보여 드려요.", 34, UI.Ink);
            }

            var picks = DailyPicker.Pick(months, today, AppState.Data.records);
            if (picks.Count == 0)
            {
                UI.Label(content, "놀이 목록을 불러오지 못했어요.", 38, UI.Sub);
                return;
            }

            int done = 0;
            string key = AgeUtil.DateKey(today);
            foreach (var p in picks) if (AppState.FindRecord(p.id, key) != null) done++;
            UI.Label(content, done >= picks.Count ? "오늘 놀이를 다 했어요!" : "하나만 골라 10분이면 충분해요", 40, UI.Ink, FontStyle.Bold);

            foreach (var p in picks) PlayCard(content, p, key);

            UI.Btn(content, "이 월령의 놀이 모두 보기", () => Go(Page.AllPlays), UI.Soft, UI.Ink, 110, 38);
            UI.Label(content, "놀이는 K-DST 발달 영역을 참고해 만든 초안이며 아직 전문가 감수 전이에요. 아이마다 속도가 다르니 못 해도 괜찮아요.",
                30, UI.Sub);
        }

        void PlayCard(Transform parent, Play p, string todayKey)
        {
            var card = UI.CardBox(parent);
            var button = card.gameObject.AddComponent<Button>();
            button.targetGraphic = card.GetComponent<Image>();
            button.onClick.AddListener(() => OpenDetail(p));

            var top = UI.HBox(card, 16);
            UI.Badge(top, Domains.Label(p.domain), Domains.ColorOf(p.domain));
            UI.Label(top, "약 " + p.minutes + "분", 32, UI.Sub, FontStyle.Normal, TextAnchor.MiddleLeft);
            UI.Spacer(top, -1, 1);
            if (AppState.FindRecord(p.id, todayKey) != null) UI.Badge(top, "했어요", UI.Good);

            UI.Label(card, p.title, 48, UI.Ink, FontStyle.Bold);
            UI.Label(card, "준비물: " + Join(p.materials), 32, UI.Sub);
        }

        void BuildAllPlays(RectTransform body)
        {
            RectTransform content;
            UI.Scroll(body, out content);
            var plays = new List<Play>(PlayRepository.ForAge(ChildMonths()));
            plays.Sort((a, b) => Array.IndexOf(Domains.All, a.domain).CompareTo(Array.IndexOf(Domains.All, b.domain)));
            if (plays.Count > 0)
                UI.Label(content, string.Format("{0}~{1}개월 놀이 {2}개", plays[0].minMonths, plays[0].maxMonths, plays.Count), 40, UI.Ink, FontStyle.Bold);
            string key = AgeUtil.DateKey(DateTime.Now);
            foreach (var p in plays) PlayCard(content, p, key);
        }

        // ───────── 놀이 상세 ─────────

        void BuildDetail(RectTransform body)
        {
            RectTransform content;
            UI.Scroll(body, out content);
            var p = _play;
            if (p == null) return;

            var top = UI.HBox(content, 16);
            UI.Badge(top, Domains.Label(p.domain), Domains.ColorOf(p.domain));
            UI.Label(top, string.Format("약 {0}분 · {1}~{2}개월", p.minutes, p.minMonths, p.maxMonths), 34, UI.Sub,
                FontStyle.Normal, TextAnchor.MiddleLeft);
            UI.Label(content, p.title, 62, UI.Ink, FontStyle.Bold);

            Section(content, "준비물", p.materials, false, UI.Card, UI.Ink);
            Section(content, "놀이 방법", p.steps, true, UI.Card, UI.Ink);
            Section(content, "이렇게 말해 주세요", p.parentTalk, false, UI.Soft, UI.Ink);
            if (!string.IsNullOrEmpty(p.tip)) Section(content, "도움말", new[] { p.tip }, false, UI.Card, UI.Ink);
            if (!string.IsNullOrEmpty(p.caution)) Section(content, "주의해 주세요", new[] { p.caution }, false, UI.Card, UI.Warn);
            UI.Label(content, "근거: " + p.source + " · AI 초안, 전문가 감수 전", 28, UI.Sub);

            // 기록
            string key = AgeUtil.DateKey(DateTime.Now);
            var existing = AppState.FindRecord(p.id, key);
            var record = UI.CardBox(content, null, 20);
            UI.Label(record, existing != null ? "오늘 기록했어요. 고칠 수 있어요." : "해 봤나요? 아이 반응은 어땠나요?", 40, UI.Ink, FontStyle.Bold);

            var buttons = new Button[4];
            Action paint = () =>
            {
                for (int i = 1; i <= 3; i++)
                {
                    bool on = _reaction == i;
                    buttons[i].GetComponent<Image>().color = on ? UI.Good : UI.Soft;
                    buttons[i].GetComponentInChildren<Text>().color = on ? Color.white : UI.Ink;
                }
            };
            for (int i = 1; i <= 3; i++)
            {
                int value = i;
                buttons[i] = UI.Btn(record, ReactionLabels[i], () =>
                {
                    _reaction = _reaction == value ? 0 : value;
                    paint();
                }, UI.Soft, UI.Ink, 100, 36);
            }
            paint();

            var memo = UI.Input(record, "한 줄 메모 (선택)", existing != null ? existing.memo : "", true, 200);
            UI.Btn(record, existing != null ? "기록 고치기" : "했어요! 기록하기", () =>
            {
                AppState.SaveRecord(p.id, key, _reaction, memo.text);
                Go(_detailBack);
            }, UI.Good);
        }

        void Section(Transform parent, string title, string[] lines, bool numbered, Color bg, Color titleColor)
        {
            if (lines == null || lines.Length == 0) return;
            var card = UI.CardBox(parent, bg, 14);
            UI.Label(card, title, 36, titleColor, FontStyle.Bold);
            for (int i = 0; i < lines.Length; i++)
            {
                string prefix = numbered ? (i + 1) + ". " : (lines.Length > 1 ? "· " : "");
                UI.Label(card, prefix + lines[i], 40, UI.Ink);
            }
        }

        // ───────── 기록 ─────────

        void BuildRecords(RectTransform body)
        {
            RectTransform content;
            UI.Scroll(body, out content);
            var records = new List<PlayRecord>(AppState.Data.records);
            if (records.Count == 0)
            {
                var empty = UI.CardBox(content);
                UI.Label(empty, "아직 기록이 없어요", 44, UI.Ink, FontStyle.Bold);
                UI.Label(empty, "홈에서 오늘의 놀이를 하나 골라 해 보고 '했어요'를 눌러 주세요.", 36, UI.Sub);
                return;
            }

            // 최근 30일 영역별 횟수
            var today = DateTime.Now.Date;
            var counts = new Dictionary<string, int>();
            int max = 1;
            foreach (var r in records)
            {
                var play = PlayRepository.Find(r.playId);
                if (play == null || (today - AgeUtil.ParseKey(r.date)).TotalDays > 30) continue;
                int c;
                counts.TryGetValue(play.domain, out c);
                counts[play.domain] = ++c;
                if (c > max) max = c;
            }

            var summary = UI.CardBox(content, null, 18);
            UI.Label(summary, "지금까지 " + records.Count + "번 놀았어요", 44, UI.Ink, FontStyle.Bold);
            UI.Label(summary, "최근 30일 · 발달 영역별", 32, UI.Sub);
            foreach (var domain in Domains.All)
            {
                int c;
                counts.TryGetValue(domain, out c);
                var row = UI.HBox(summary, 16);
                var name = UI.Label(row, Domains.Label(domain), 34, UI.Ink, FontStyle.Normal, TextAnchor.MiddleLeft);
                UI.Size(name, 150);
                var barNode = UI.Node("Bar", row);
                UI.Fill(barNode, Domains.ColorOf(domain), true).raycastTarget = false;
                UI.Size(barNode, 48f + 520f * c / max, 36);
                UI.Label(row, c + "번", 34, UI.Sub, FontStyle.Normal, TextAnchor.MiddleLeft);
            }

            records.Sort((a, b) => string.CompareOrdinal(b.date, a.date));
            foreach (var r in records)
            {
                var record = r;
                var play = PlayRepository.Find(r.playId);
                var card = UI.CardBox(content);
                var top = UI.HBox(card, 16);
                var d = AgeUtil.ParseKey(r.date);
                UI.Label(top, string.Format("{0}월 {1}일", d.Month, d.Day), 32, UI.Sub, FontStyle.Normal, TextAnchor.MiddleLeft);
                if (play != null) UI.Badge(top, Domains.Label(play.domain), Domains.ColorOf(play.domain));
                UI.Spacer(top, -1, 1);
                UI.Size(UI.Btn(top, "지우기", () => { AppState.DeleteRecord(record); Render(); }, UI.Soft, UI.Sub, 72, 28), 150);

                UI.Label(card, play != null ? play.title : "(없어진 놀이)", 44, UI.Ink, FontStyle.Bold);
                if (r.reaction >= 1 && r.reaction <= 3) UI.Label(card, ReactionLabels[r.reaction], 34, UI.Good);
                if (!string.IsNullOrEmpty(r.memo)) UI.Label(card, r.memo, 36, UI.Ink);
            }
        }

        // ───────── 수면 ─────────

        void BuildSleep(RectTransform body)
        {
            RectTransform content;
            UI.Scroll(body, out content);
            var data = AppState.Data;

            var status = UI.CardBox(content, NightCard);
            _sleepStatus = UI.Label(status, SleepStatusText(), 40, Color.white, FontStyle.Bold, TextAnchor.MiddleCenter);

            for (int i = 0; i < SleepAudioPlayer.SoundNames.Length; i++)
            {
                int index = i;
                bool on = _audio.IsPlaying && _audio.CurrentIndex == i;
                UI.Btn(content, (on ? "■  " : "▶  ") + SleepAudioPlayer.SoundNames[i], () =>
                {
                    if (_audio.IsPlaying && _audio.CurrentIndex == index) _audio.Stop();
                    else _audio.Play(index, AppState.Data.timerMinutes);
                    Render();
                }, on ? UI.Primary : NightCard, Color.white, 120, 40);
            }

            var volumeCard = UI.CardBox(content, NightCard, 16);
            UI.Label(volumeCard, "음량", 32, new Color(1, 1, 1, 0.7f));
            var row = UI.HBox(volumeCard, 16);
            Text volumeText = null;
            Action<float> changeVolume = delta =>
            {
                data.volume = Mathf.Clamp(Mathf.Round((data.volume + delta) * 10f) / 10f, 0.1f, 1f);
                _audio.SetVolume(data.volume);
                volumeText.text = Mathf.RoundToInt(data.volume * 100f) + "%";
                AppState.Save();
            };
            UI.Size(UI.Btn(row, "-", () => changeVolume(-0.1f), UI.Night, Color.white, 110, 52), 150);
            volumeText = UI.Label(row, Mathf.RoundToInt(data.volume * 100f) + "%", 46, Color.white, FontStyle.Bold, TextAnchor.MiddleCenter);
            UI.Size(volumeText, -1, -1, 1);
            UI.Size(UI.Btn(row, "+", () => changeVolume(0.1f), UI.Night, Color.white, 110, 52), 150);

            var timerCard = UI.CardBox(content, NightCard, 16);
            UI.Label(timerCard, "꺼짐 타이머", 32, new Color(1, 1, 1, 0.7f));
            var timers = UI.HBox(timerCard, 12);
            foreach (int option in TimerOptions)
            {
                int minutes = option;
                bool on = data.timerMinutes == minutes;
                var b = UI.Btn(timers, minutes == 0 ? "계속" : minutes + "분", () =>
                {
                    data.timerMinutes = minutes;
                    if (_audio.IsPlaying) _audio.SetTimer(minutes);
                    AppState.Save();
                    Render();
                }, on ? UI.Primary : UI.Night, Color.white, 100, 36);
                UI.Size(b, -1, -1, 1);
            }

            UI.Label(content,
                "기기는 아기 머리에서 2m 이상 떨어진 곳에 두고, 조용히 말하는 소리보다 작게 틀어 주세요. " +
                "밤새 켜 두기보다 잠들 때까지만 쓰는 걸 권해요.\n" +
                "화면을 끄거나 다른 앱으로 나가면 소리가 멈출 수 있어요.",
                30, new Color(1, 1, 1, 0.7f));
        }

        string SleepStatusText()
        {
            if (_audio == null || !_audio.IsPlaying) return "소리를 골라 주세요";
            string name = SleepAudioPlayer.SoundNames[_audio.CurrentIndex];
            if (!_audio.TimerOn) return name + "\n계속 재생 중";
            int seconds = Mathf.CeilToInt(_audio.RemainingSeconds);
            return string.Format("{0}\n{1}:{2:00} 뒤에 꺼져요", name, seconds / 60, seconds % 60);
        }

        // ───────── 부모 화면 ─────────

        void BuildParent(RectTransform body)
        {
            RectTransform content;
            UI.Scroll(body, out content);
            var c = AppState.Data.child;

            var childCard = UI.CardBox(content);
            UI.Label(childCard, c.name, 50, UI.Ink, FontStyle.Bold);
            UI.Label(childCard, string.Format("{0}년 {1}월 {2}일생 · {3}", c.birthYear, c.birthMonth, c.birthDay,
                AgeUtil.AgeLabel(ChildMonths())), 36, UI.Sub);
            UI.Btn(childCard, "아이 정보 수정", () => { PrepareRegister(); Go(Page.Register); }, UI.Soft, UI.Ink, 100, 36);

            var about = UI.CardBox(content);
            UI.Label(about, "이 앱은요", 40, UI.Ink, FontStyle.Bold);
            UI.Label(about, "결제 압박 없는 무료 앱이에요. 구독도, 맞춤 광고도 없어요. 아이 정보와 기록은 이 기기에만 저장돼요.", 36, UI.Ink);

            var support = UI.CardBox(content);
            UI.Label(support, "응원하기", 40, UI.Ink, FontStyle.Bold);
            UI.Label(support, "도움이 됐다면 후원으로 응원해 주세요. 하지 않아도 모든 기능을 그대로 쓸 수 있어요.", 36, UI.Ink);
            UI.Btn(support, "후원하기", () =>
            {
                if (string.IsNullOrEmpty(SupportUrl))
                {
                    _confirmReset = false;
                    _notice = "후원 기능은 준비 중이에요. 마음만으로도 고마워요.";
                    Render();
                }
                else Application.OpenURL(SupportUrl);
            }, UI.Primary, Color.white, 100, 36);
            if (_notice.Length > 0) UI.Label(support, _notice, 32, UI.Good);

            var basis = UI.CardBox(content);
            UI.Label(basis, "근거와 한계", 40, UI.Ink, FontStyle.Bold);
            UI.Label(basis,
                "놀이는 한국 영유아 발달선별검사(K-DST)의 월령 구간과 발달 영역을 참고해 만든 초안이에요. " +
                "아직 전문가 감수를 받지 않았고, 발달 평가나 진단을 대신하지 않아요. " +
                "발달이 걱정되면 영유아 건강검진이나 소아청소년과에서 상담해 주세요.", 34, UI.Sub);

            UI.Btn(content, _confirmReset ? "정말 지울까요? 한 번 더 누르면 지워져요" : "모든 데이터 지우기", () =>
            {
                if (!_confirmReset)
                {
                    _confirmReset = true;
                    _notice = "";
                    Render();
                    return;
                }
                _audio.Stop();
                AppState.Reset();
                _audio.SetVolume(AppState.Data.volume);
                PrepareRegister();
                Go(Page.Register);
            }, _confirmReset ? UI.Warn : UI.Soft, _confirmReset ? Color.white : UI.Warn, 100, 34);

            UI.Label(content, "오늘의 놀이 v" + Application.version, 28, UI.Sub, FontStyle.Normal, TextAnchor.MiddleCenter);
        }

        static string Join(string[] items)
        {
            return items == null || items.Length == 0 ? "없음" : string.Join(", ", items);
        }
    }
}
