using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace KidsPlayGuide
{
    [Serializable]
    public class ChildProfile
    {
        public string name = "";
        public int birthYear;
        public int birthMonth;
        public int birthDay;

        public DateTime BirthDate
        {
            get { return AgeUtil.SafeDate(birthYear, birthMonth, birthDay); }
        }
    }

    [Serializable]
    public class PlayRecord
    {
        public string playId;
        public string date;     // yyyy-MM-dd
        public int reaction;    // 0 선택 안 함, 1 좋아했어요, 2 보통, 3 관심 없음
        public string memo = "";
    }

    [Serializable]
    public class SaveData
    {
        public bool hasChild;
        public ChildProfile child = new ChildProfile();
        public List<PlayRecord> records = new List<PlayRecord>();
        public float volume = 0.3f;
        public int timerMinutes = 30;
    }

    /// <summary>아이 정보와 기록. 기기 로컬(persistentDataPath)에만 저장한다.</summary>
    public static class AppState
    {
        public static SaveData Data = new SaveData();

        static string FilePath
        {
            get { return Path.Combine(Application.persistentDataPath, "save.json"); }
        }

        public static void Load()
        {
            try
            {
                if (File.Exists(FilePath))
                {
                    var loaded = JsonUtility.FromJson<SaveData>(File.ReadAllText(FilePath));
                    if (loaded != null) Data = loaded;
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("저장 파일을 읽지 못했습니다: " + e.Message);
            }
            if (Data.child == null) Data.child = new ChildProfile();
            if (Data.records == null) Data.records = new List<PlayRecord>();
        }

        public static void Save()
        {
            try
            {
                File.WriteAllText(FilePath, JsonUtility.ToJson(Data));
            }
            catch (Exception e)
            {
                Debug.LogWarning("저장하지 못했습니다: " + e.Message);
            }
        }

        public static void Reset()
        {
            Data = new SaveData();
            Save();
        }

        public static PlayRecord FindRecord(string playId, string date)
        {
            foreach (var r in Data.records)
                if (r.playId == playId && r.date == date) return r;
            return null;
        }

        public static void SaveRecord(string playId, string date, int reaction, string memo)
        {
            var r = FindRecord(playId, date);
            if (r == null)
            {
                r = new PlayRecord { playId = playId, date = date };
                Data.records.Add(r);
            }
            r.reaction = reaction;
            r.memo = memo ?? "";
            Save();
        }

        public static void DeleteRecord(PlayRecord record)
        {
            Data.records.Remove(record);
            Save();
        }
    }

    public static class AgeUtil
    {
        public static string DateKey(DateTime d)
        {
            return d.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        }

        public static DateTime ParseKey(string key)
        {
            DateTime d;
            if (DateTime.TryParseExact(key, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out d))
                return d;
            return DateTime.MinValue;
        }

        public static DateTime SafeDate(int y, int m, int d)
        {
            y = Mathf.Clamp(y, 1, 9999);
            m = Mathf.Clamp(m, 1, 12);
            d = Mathf.Clamp(d, 1, DateTime.DaysInMonth(y, m));
            return new DateTime(y, m, d);
        }

        /// <summary>만 개월 수. 생일 날짜가 아직 안 지났으면 한 달을 뺀다.</summary>
        public static int MonthsOld(DateTime birth, DateTime today)
        {
            int months = (today.Year - birth.Year) * 12 + (today.Month - birth.Month);
            if (today.Day < birth.Day) months--;
            return Mathf.Max(0, months);
        }

        public static string AgeLabel(int months)
        {
            if (months < 24) return months + "개월";
            int years = months / 12, rest = months % 12;
            return rest == 0
                ? string.Format("{0}개월 (만 {1}세)", months, years)
                : string.Format("{0}개월 (만 {1}세 {2}개월)", months, years, rest);
        }
    }

    /// <summary>오늘의 놀이 3개를 고른다. 같은 날에는 항상 같은 결과가 나온다.</summary>
    public static class DailyPicker
    {
        public const int Count = 3;

        public static List<Play> Pick(int months, DateTime today, List<PlayRecord> records)
        {
            var pool = new List<Play>(PlayRepository.ForAge(months));
            var rng = new System.Random(today.Year * 10000 + today.Month * 100 + today.Day);

            // 날짜 시드로 섞기 (Fisher–Yates)
            for (int i = pool.Count - 1; i > 0; i--)
            {
                int j = rng.Next(i + 1);
                var t = pool[i]; pool[i] = pool[j]; pool[j] = t;
            }

            // 최근 7일 안에(오늘 제외) 한 놀이는 뒤로 미룬다.
            var recent = new HashSet<string>();
            foreach (var r in records)
            {
                var d = AgeUtil.ParseKey(r.date);
                double days = (today - d).TotalDays;
                if (days >= 1 && days <= 7) recent.Add(r.playId);
            }
            var ordered = new List<Play>();
            foreach (var p in pool) if (!recent.Contains(p.id)) ordered.Add(p);
            foreach (var p in pool) if (recent.Contains(p.id)) ordered.Add(p);
            pool = ordered;

            // 발달 영역이 겹치지 않게 먼저 고르고, 모자라면 남은 것으로 채운다.
            var picked = new List<Play>();
            var usedDomains = new HashSet<string>();
            foreach (var p in pool)
            {
                if (picked.Count >= Count) break;
                if (usedDomains.Add(p.domain)) picked.Add(p);
            }
            foreach (var p in pool)
            {
                if (picked.Count >= Count) break;
                if (!picked.Contains(p)) picked.Add(p);
            }
            return picked;
        }
    }
}
