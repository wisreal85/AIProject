using System;
using UnityEngine;

namespace KidsPlayGuide
{
    /// <summary>
    /// 수면용 소리. 음원 파일 없이 코드로 합성하므로 저작권 문제가 없다.
    /// 백색·분홍·갈색 소음과, 저작권이 만료된 선율 2곡(브람스 자장가, 작은 별).
    /// </summary>
    public class SleepAudioPlayer : MonoBehaviour
    {
        public static readonly string[] SoundNames =
        {
            "백색소음 (쉬—)", "분홍소음 (빗소리 느낌)", "갈색소음 (낮은 웅— 소리)", "브람스 자장가", "반짝반짝 작은 별"
        };

        const int SampleRate = 44100;
        const float FadeSeconds = 20f;

        AudioSource _source;
        readonly AudioClip[] _clips = new AudioClip[SoundNames.Length];
        float _remaining;      // 남은 타이머(초). 0 이하면 타이머 없음.
        bool _timerOn;
        float _userVolume = 0.3f;

        public int CurrentIndex { get; private set; }
        public bool IsPlaying { get { return _source != null && _source.isPlaying; } }
        public bool TimerOn { get { return _timerOn && IsPlaying; } }
        public float RemainingSeconds { get { return _remaining; } }

        void Awake()
        {
            CurrentIndex = -1;
            _source = gameObject.AddComponent<AudioSource>();
            _source.loop = true;
            _source.playOnAwake = false;
            _source.spatialBlend = 0f;
        }

        public void SetVolume(float volume)
        {
            _userVolume = Mathf.Clamp01(volume);
            if (_source != null) _source.volume = _userVolume * FadeFactor();
        }

        /// <param name="timerMinutes">0 이면 계속 재생.</param>
        public void Play(int index, int timerMinutes)
        {
            if (index < 0 || index >= SoundNames.Length) return;
            if (_clips[index] == null) _clips[index] = BuildClip(index);
            CurrentIndex = index;
            _source.clip = _clips[index];
            SetTimer(timerMinutes);
            _source.volume = _userVolume;
            _source.Play();
        }

        public void SetTimer(int minutes)
        {
            _timerOn = minutes > 0;
            _remaining = minutes * 60f;
            if (_source != null) _source.volume = _userVolume * FadeFactor();
        }

        public void Stop()
        {
            if (_source != null) _source.Stop();
            _timerOn = false;
            CurrentIndex = -1;
        }

        float FadeFactor()
        {
            if (!_timerOn) return 1f;
            return Mathf.Clamp01(_remaining / FadeSeconds);
        }

        void Update()
        {
            if (!_timerOn || !_source.isPlaying) return;
            _remaining -= Time.unscaledDeltaTime;
            if (_remaining <= 0f)
            {
                Stop();
                return;
            }
            _source.volume = _userVolume * FadeFactor();
        }

        // ───────── 합성 ─────────

        AudioClip BuildClip(int index)
        {
            float[] data;
            switch (index)
            {
                case 0: data = Noise(0); break;
                case 1: data = Noise(1); break;
                case 2: data = Noise(2); break;
                case 3: data = Melody(BrahmsNotes, BrahmsBeats, 66f); break;
                default: data = Melody(TwinkleNotes, TwinkleBeats, 72f); break;
            }
            var clip = AudioClip.Create(SoundNames[index], data.Length, 1, SampleRate, false);
            clip.SetData(data, 0);
            return clip;
        }

        /// <summary>kind: 0 백색, 1 분홍, 2 갈색. 이음매가 튀지 않게 앞뒤를 겹쳐 이어 붙인다.</summary>
        static float[] Noise(int kind)
        {
            int length = SampleRate * 12;
            int overlap = SampleRate / 2;
            var raw = new float[length + overlap];
            var rng = new System.Random(1234 + kind);

            float b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0, brown = 0;
            for (int i = 0; i < raw.Length; i++)
            {
                float white = (float)(rng.NextDouble() * 2.0 - 1.0);
                if (kind == 0)
                {
                    raw[i] = white * 0.25f;
                }
                else if (kind == 1)
                {
                    // Paul Kellet 의 분홍소음 근사 필터
                    b0 = 0.99886f * b0 + white * 0.0555179f;
                    b1 = 0.99332f * b1 + white * 0.0750759f;
                    b2 = 0.96900f * b2 + white * 0.1538520f;
                    b3 = 0.86650f * b3 + white * 0.3104856f;
                    b4 = 0.55000f * b4 + white * 0.5329522f;
                    b5 = -0.7616f * b5 - white * 0.0168980f;
                    raw[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362f) * 0.06f;
                    b6 = white * 0.115926f;
                }
                else
                {
                    brown = (brown + white * 0.02f) / 1.02f;
                    raw[i] = brown * 2.2f;
                }
            }

            var data = new float[length];
            for (int i = 0; i < length; i++)
            {
                if (i < overlap)
                {
                    // 끝부분(겹침 구간)에서 시작 부분으로 같은 세기(equal-power)로 넘어간다.
                    float t = (float)i / overlap;
                    data[i] = raw[i] * Mathf.Sin(t * Mathf.PI * 0.5f) + raw[length + i] * Mathf.Cos(t * Mathf.PI * 0.5f);
                }
                else
                {
                    data[i] = raw[i];
                }
            }
            return data;
        }

        // MIDI 음높이 (60 = 가온 도). 0 은 쉼표.
        static readonly int[] BrahmsNotes =
        {
            64, 64, 67, 64, 64, 67, 64, 67, 72, 71, 69, 69, 67, 62, 64, 65, 62, 62, 64, 65, 62, 65, 71, 69, 67, 71, 72,
            60, 60, 72, 69, 65, 67, 64, 60, 65, 67, 69, 67, 60, 60, 72, 69, 65, 67, 64, 60, 65, 64, 62, 60, 0
        };
        static readonly float[] BrahmsBeats =
        {
            .5f, .5f, 1.5f, .5f, 1f, 2f, .5f, .5f, 1f, 1.5f, .5f, 1f, 1f, .5f, .5f, 1f, 1f, .5f, .5f, 2f, .5f, .5f, .5f, .5f, 1f, 1f, 2f,
            .5f, .5f, 2f, .5f, .5f, 2f, .5f, .5f, 1f, 1f, 1f, 2f, .5f, .5f, 2f, .5f, .5f, 2f, .5f, .5f, 1f, 1f, 1f, 3f, 2f
        };

        static readonly int[] TwinkleNotes =
        {
            60, 60, 67, 67, 69, 69, 67, 65, 65, 64, 64, 62, 62, 60,
            67, 67, 65, 65, 64, 64, 62, 67, 67, 65, 65, 64, 64, 62,
            60, 60, 67, 67, 69, 69, 67, 65, 65, 64, 64, 62, 62, 60, 0
        };
        static readonly float[] TwinkleBeats =
        {
            1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 2,
            1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 2,
            1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 2, 2
        };

        /// <summary>오르골 느낌의 부드러운 음색으로 선율을 합성한다.</summary>
        static float[] Melody(int[] notes, float[] beats, float bpm)
        {
            float beatSeconds = 60f / bpm;
            float total = 0f;
            for (int i = 0; i < beats.Length; i++) total += beats[i];
            var data = new float[Mathf.CeilToInt(total * beatSeconds * SampleRate)];

            float start = 0f;
            int count = Mathf.Min(notes.Length, beats.Length);
            for (int n = 0; n < count; n++)
            {
                float duration = beats[n] * beatSeconds;
                if (notes[n] > 0)
                {
                    double freq = 440.0 * Math.Pow(2.0, (notes[n] - 69) / 12.0);
                    int from = Mathf.RoundToInt(start * SampleRate);
                    // 다음 음과 살짝 겹치도록 여운을 남긴다.
                    int len = Mathf.RoundToInt((duration + 0.6f) * SampleRate);
                    for (int i = 0; i < len; i++)
                    {
                        float t = (float)i / SampleRate;
                        float attack = Mathf.Clamp01(t / 0.02f);
                        float decay = Mathf.Exp(-t * 2.2f / Mathf.Max(0.5f, duration));
                        double phase = 2.0 * Math.PI * freq * t;
                        float s = (float)(Math.Sin(phase) + 0.25 * Math.Sin(phase * 2.0) + 0.08 * Math.Sin(phase * 3.0));
                        // 반복 재생이므로 끝을 넘는 여운은 처음으로 넘겨 이음매를 자연스럽게 만든다.
                        data[(from + i) % data.Length] += s * attack * decay * 0.22f;
                    }
                }
                start += duration;
            }
            return data;
        }
    }
}
