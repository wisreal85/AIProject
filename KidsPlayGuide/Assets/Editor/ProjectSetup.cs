using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine.SceneManagement;

namespace KidsPlayGuide.EditorTools
{
    /// <summary>
    /// 프로젝트를 처음 열 때 한 번 실행되는 설정.
    /// 기본 씬(Assets/Scenes/Main.unity)을 만들어 빌드 목록에 넣고, 앱 이름과 세로 고정을 맞춘다.
    /// </summary>
    [InitializeOnLoad]
    static class ProjectSetup
    {
        const string ScenePath = "Assets/Scenes/Main.unity";
        const string ProductName = "오늘의 놀이";

        static ProjectSetup()
        {
            EditorApplication.delayCall += Run;
        }

        static void Run()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode) return;

            if (!File.Exists(ScenePath))
            {
                var active = SceneManager.GetActiveScene();
                if (active.isDirty && !string.IsNullOrEmpty(active.path)) return; // 작업 중인 씬은 건드리지 않는다.
                Directory.CreateDirectory(Path.GetDirectoryName(ScenePath));
                var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
                EditorSceneManager.SaveScene(scene, ScenePath);
                AssetDatabase.Refresh();
            }

            var scenes = new List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
            if (!scenes.Exists(s => s.path == ScenePath))
            {
                scenes.Insert(0, new EditorBuildSettingsScene(ScenePath, true));
                EditorBuildSettings.scenes = scenes.ToArray();
            }

            if (PlayerSettings.productName != ProductName)
            {
                PlayerSettings.productName = ProductName;
                PlayerSettings.defaultInterfaceOrientation = UIOrientation.Portrait;
            }
        }
    }
}
