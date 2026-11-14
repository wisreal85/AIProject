using System;
using System.Collections.Generic;
using UnityEngine;

namespace KidsPlayGuide
{
    /// <summary>놀이 한 개. Assets/Resources/plays.json 의 항목과 1:1 대응.</summary>
    [Serializable]
    public class Play
    {
        public string id;
        public string title;
        public int minMonths;
        public int maxMonths;
        public string domain;      // gross | fine | language | cognition | social
        public int minutes;
        public string[] materials;
        public string[] steps;
        public string[] parentTalk;
        public string tip;
        public string caution;
        public string source;
    }

    [Serializable]
    public class PlayCatalog
    {
        public List<Play> plays = new List<Play>();
    }

    public static class Domains
    {
        public static readonly string[] All = { "gross", "fine", "language", "cognition", "social" };

        public static string Label(string domain)
        {
            switch (domain)
            {
                case "gross": return "대근육";
                case "fine": return "소근육";
                case "language": return "언어";
                case "cognition": return "인지";
                case "social": return "사회성";
                default: return domain;
            }
        }

        public static Color ColorOf(string domain)
        {
            switch (domain)
            {
                case "gross": return new Color32(0xF2, 0x8B, 0x50, 0xFF);
                case "fine": return new Color32(0x4F, 0xA8, 0x8B, 0xFF);
                case "language": return new Color32(0x5B, 0x8D, 0xD9, 0xFF);
                case "cognition": return new Color32(0x9A, 0x6F, 0xD0, 0xFF);
                case "social": return new Color32(0xE0, 0x6C, 0x8F, 0xFF);
                default: return new Color32(0x88, 0x88, 0x88, 0xFF);
            }
        }
    }

    public static class PlayRepository
    {
        static List<Play> _plays;

        public static List<Play> All
        {
            get
            {
                if (_plays == null) Load();
                return _plays;
            }
        }

        static void Load()
        {
            _plays = new List<Play>();
            var asset = Resources.Load<TextAsset>("plays");
            if (asset == null)
            {
                Debug.LogError("Resources/plays.json 을 찾을 수 없습니다.");
                return;
            }
            var catalog = JsonUtility.FromJson<PlayCatalog>(asset.text);
            if (catalog != null && catalog.plays != null) _plays = catalog.plays;
        }

        public static Play Find(string id)
        {
            foreach (var p in All) if (p.id == id) return p;
            return null;
        }

        /// <summary>
        /// 월령에 맞는 놀이. 콘텐츠 범위(12~36개월)를 벗어나면 가장 가까운 구간을 돌려준다.
        /// </summary>
        public static List<Play> ForAge(int months)
        {
            int lo = int.MaxValue, hi = int.MinValue;
            foreach (var p in All)
            {
                if (p.minMonths < lo) lo = p.minMonths;
                if (p.maxMonths > hi) hi = p.maxMonths;
            }
            if (All.Count > 0) months = Mathf.Clamp(months, lo, hi);

            var result = new List<Play>();
            foreach (var p in All)
                if (months >= p.minMonths && months <= p.maxMonths) result.Add(p);
            return result;
        }

        public static bool IsAgeCovered(int months)
        {
            foreach (var p in All)
                if (months >= p.minMonths && months <= p.maxMonths) return true;
            return false;
        }
    }
}
