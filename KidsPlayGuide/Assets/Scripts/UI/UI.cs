using System;
using UnityEngine;
using UnityEngine.UI;

namespace KidsPlayGuide
{
    /// <summary>uGUI 요소를 코드로 만드는 도우미. 씬·프리팹 연결 없이 화면 전체를 구성한다.</summary>
    public static class UI
    {
        public static readonly Color Bg = new Color32(0xFF, 0xF8, 0xEE, 0xFF);
        public static readonly Color Card = Color.white;
        public static readonly Color Ink = new Color32(0x3A, 0x33, 0x2C, 0xFF);
        public static readonly Color Sub = new Color32(0x8A, 0x80, 0x76, 0xFF);
        public static readonly Color Primary = new Color32(0xF2, 0x8B, 0x50, 0xFF);
        public static readonly Color Soft = new Color32(0xF3, 0xEA, 0xDD, 0xFF);
        public static readonly Color Good = new Color32(0x4F, 0xA8, 0x8B, 0xFF);
        public static readonly Color Warn = new Color32(0xC9, 0x54, 0x4B, 0xFF);
        public static readonly Color Night = new Color32(0x2B, 0x30, 0x4F, 0xFF);

        static Font _font;
        static Sprite _round;

        public static Font AppFont
        {
            get
            {
                if (_font == null) _font = LoadFont();
                return _font;
            }
        }

        static Font LoadFont()
        {
            // 한글이 들어 있는 OS 글꼴을 먼저 찾고, 없으면 유니티 기본 글꼴(OS 대체 글꼴 사용)로 간다.
            string[] names =
            {
                "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans CJK KR", "Noto Sans KR", "NanumGothic", "Roboto", "Arial"
            };
            try
            {
                var f = Font.CreateDynamicFontFromOSFont(names, 32);
                if (f != null) return f;
            }
            catch (Exception) { }
            return Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        }

        /// <summary>모서리가 둥근 흰색 9-slice 스프라이트.</summary>
        public static Sprite Round
        {
            get
            {
                if (_round != null) return _round;
                const int size = 64;
                const float radius = 22f;
                var tex = new Texture2D(size, size, TextureFormat.RGBA32, false);
                tex.wrapMode = TextureWrapMode.Clamp;
                tex.hideFlags = HideFlags.HideAndDontSave;
                var pixels = new Color32[size * size];
                for (int y = 0; y < size; y++)
                {
                    for (int x = 0; x < size; x++)
                    {
                        float cx = Mathf.Clamp(x + 0.5f, radius, size - radius);
                        float cy = Mathf.Clamp(y + 0.5f, radius, size - radius);
                        float dist = Vector2.Distance(new Vector2(x + 0.5f, y + 0.5f), new Vector2(cx, cy));
                        float alpha = Mathf.Clamp01(radius - dist + 0.5f);
                        pixels[y * size + x] = new Color(1f, 1f, 1f, alpha);
                    }
                }
                tex.SetPixels32(pixels);
                tex.Apply();
                _round = Sprite.Create(tex, new Rect(0, 0, size, size), new Vector2(0.5f, 0.5f), 100f, 0,
                    SpriteMeshType.FullRect, new Vector4(24, 24, 24, 24));
                _round.hideFlags = HideFlags.HideAndDontSave;
                return _round;
            }
        }

        public static RectTransform Node(string name, Transform parent)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.layer = 5; // UI
            var rt = (RectTransform)go.transform;
            rt.SetParent(parent, false);
            return rt;
        }

        public static RectTransform Stretch(RectTransform rt, float left = 0, float top = 0, float right = 0, float bottom = 0)
        {
            rt.anchorMin = Vector2.zero;
            rt.anchorMax = Vector2.one;
            rt.offsetMin = new Vector2(left, bottom);
            rt.offsetMax = new Vector2(-right, -top);
            return rt;
        }

        public static Image Fill(RectTransform rt, Color color, bool rounded)
        {
            var img = rt.gameObject.AddComponent<Image>();
            img.color = color;
            if (rounded)
            {
                img.sprite = Round;
                img.type = Image.Type.Sliced;
            }
            return img;
        }

        public static LayoutElement Size(Component c, float width = -1, float height = -1, float flexW = -1, float flexH = -1)
        {
            var le = c.GetComponent<LayoutElement>();
            if (le == null) le = c.gameObject.AddComponent<LayoutElement>();
            if (width >= 0) { le.minWidth = width; le.preferredWidth = width; }
            if (height >= 0) { le.minHeight = height; le.preferredHeight = height; }
            if (flexW >= 0) le.flexibleWidth = flexW;
            if (flexH >= 0) le.flexibleHeight = flexH;
            return le;
        }

        public static RectTransform VBox(Transform parent, float spacing = 16, int padding = 0, string name = "VBox")
        {
            var rt = Node(name, parent);
            var g = rt.gameObject.AddComponent<VerticalLayoutGroup>();
            g.spacing = spacing;
            g.padding = new RectOffset(padding, padding, padding, padding);
            g.childControlWidth = true;
            g.childControlHeight = true;
            g.childForceExpandWidth = true;
            g.childForceExpandHeight = false;
            g.childAlignment = TextAnchor.UpperLeft;
            return rt;
        }

        public static RectTransform HBox(Transform parent, float spacing = 12, string name = "HBox")
        {
            var rt = Node(name, parent);
            var g = rt.gameObject.AddComponent<HorizontalLayoutGroup>();
            g.spacing = spacing;
            g.childControlWidth = true;
            g.childControlHeight = true;
            g.childForceExpandWidth = false;
            g.childForceExpandHeight = false;
            g.childAlignment = TextAnchor.MiddleLeft;
            return rt;
        }

        /// <summary>흰 배경의 둥근 카드(세로 배치).</summary>
        public static RectTransform CardBox(Transform parent, Color? color = null, float spacing = 12, int padding = 36)
        {
            var rt = VBox(parent, spacing, padding, "Card");
            Fill(rt, color ?? Card, true);
            return rt;
        }

        public static Text Label(Transform parent, string text, int size = 40, Color? color = null,
            FontStyle style = FontStyle.Normal, TextAnchor align = TextAnchor.UpperLeft)
        {
            var rt = Node("Label", parent);
            var t = rt.gameObject.AddComponent<Text>();
            t.font = AppFont;
            t.text = text ?? "";
            t.fontSize = size;
            t.fontStyle = style;
            t.color = color ?? Ink;
            t.alignment = align;
            t.lineSpacing = 1.15f;
            t.horizontalOverflow = HorizontalWrapMode.Wrap;
            t.verticalOverflow = VerticalWrapMode.Overflow;
            t.supportRichText = false;
            t.raycastTarget = false;
            return t;
        }

        public static Button Btn(Transform parent, string label, Action onClick, Color? bg = null, Color? fg = null,
            float height = 120, int fontSize = 40)
        {
            var rt = Node("Button", parent);
            var img = Fill(rt, bg ?? Primary, true);
            var b = rt.gameObject.AddComponent<Button>();
            b.targetGraphic = img;
            if (onClick != null) b.onClick.AddListener(() => onClick());
            Size(rt, -1, height);

            var t = Label(rt, label, fontSize, fg ?? Color.white, FontStyle.Bold, TextAnchor.MiddleCenter);
            t.horizontalOverflow = HorizontalWrapMode.Overflow;
            Stretch(t.rectTransform, 12, 0, 12, 0);
            return b;
        }

        /// <summary>둥근 색 배지(짧은 글자).</summary>
        public static RectTransform Badge(Transform parent, string text, Color color)
        {
            var rt = Node("Badge", parent);
            Fill(rt, color, true).raycastTarget = false;
            var g = rt.gameObject.AddComponent<HorizontalLayoutGroup>();
            g.padding = new RectOffset(24, 24, 8, 8);
            g.childControlWidth = true;
            g.childControlHeight = true;
            g.childForceExpandWidth = false;
            g.childForceExpandHeight = false;
            g.childAlignment = TextAnchor.MiddleCenter;
            var t = Label(rt, text, 30, Color.white, FontStyle.Bold, TextAnchor.MiddleCenter);
            t.horizontalOverflow = HorizontalWrapMode.Overflow;
            Size(rt, -1, -1, 0, 0);
            return rt;
        }

        public static RectTransform Spacer(Transform parent, float height = 0, float flexW = -1)
        {
            var rt = Node("Spacer", parent);
            Size(rt, -1, height >= 0 ? height : -1, flexW);
            return rt;
        }

        /// <summary>세로 스크롤 영역. content 에 자식을 추가하면 된다.</summary>
        public static RectTransform Scroll(Transform parent, out RectTransform content, int padding = 40, float spacing = 28)
        {
            var root = Node("Scroll", parent);
            Stretch(root);
            var hit = root.gameObject.AddComponent<Image>();
            hit.color = new Color(0, 0, 0, 0);

            var scroll = root.gameObject.AddComponent<ScrollRect>();
            scroll.horizontal = false;
            scroll.vertical = true;
            scroll.movementType = ScrollRect.MovementType.Elastic;
            scroll.scrollSensitivity = 60f;

            var viewport = Node("Viewport", root);
            Stretch(viewport);
            viewport.gameObject.AddComponent<RectMask2D>();

            content = VBox(viewport, spacing, padding, "Content");
            content.anchorMin = new Vector2(0, 1);
            content.anchorMax = new Vector2(1, 1);
            content.pivot = new Vector2(0.5f, 1);
            content.offsetMin = Vector2.zero;
            content.offsetMax = Vector2.zero;
            var fitter = content.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            scroll.viewport = viewport;
            scroll.content = content;
            return root;
        }

        public static InputField Input(Transform parent, string placeholder, string value, bool multiline = false, int limit = 0)
        {
            var rt = Node("Input", parent);
            var img = Fill(rt, Soft, true);
            Size(rt, -1, multiline ? 240 : 120);

            var text = Label(rt, "", 40, Ink, FontStyle.Normal, multiline ? TextAnchor.UpperLeft : TextAnchor.MiddleLeft);
            Stretch(text.rectTransform, 32, 20, 32, 20);
            if (!multiline) text.horizontalOverflow = HorizontalWrapMode.Overflow;
            text.verticalOverflow = VerticalWrapMode.Truncate;

            var hint = Label(rt, placeholder, 40, Sub, FontStyle.Normal, multiline ? TextAnchor.UpperLeft : TextAnchor.MiddleLeft);
            Stretch(hint.rectTransform, 32, 20, 32, 20);

            var input = rt.gameObject.AddComponent<InputField>();
            input.targetGraphic = img;
            input.textComponent = text;
            input.placeholder = hint;
            input.lineType = multiline ? InputField.LineType.MultiLineNewline : InputField.LineType.SingleLine;
            input.characterLimit = limit;
            input.text = value ?? "";
            return input;
        }
    }
}
