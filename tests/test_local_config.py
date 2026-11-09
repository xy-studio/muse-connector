import ast
import importlib.util
import json
import shutil
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class AgentConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        (self.directory / "project").mkdir()
        self.config = self.directory / "config.local.json"
        self.write_config({"base_dir": "project"})
        source = self.directory / "win_agent.py"
        shutil.copyfile(ROOT / "src" / "win_agent.py", source)
        spec = importlib.util.spec_from_file_location("muse_test_agent", source)
        self.agent = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.agent)

    def write_config(self, value, encoding="utf-8"):
        self.config.write_text(json.dumps(value), encoding=encoding)

    def request(self, path, headers=None):
        handler = self.agent.Handler.__new__(self.agent.Handler)
        handler.client_address = ("127.0.0.1", 0)
        handler.path = path
        handler.headers = Message()
        for key, value in (headers or {}).items():
            handler.headers[key] = value
        handler._send = Mock()
        with patch.object(self.agent, "log"):
            handler.do_GET()
        return handler._send.call_args.args

    def test_relative_base_is_relative_to_agent_directory(self):
        self.assertEqual(self.agent.BASE, (self.directory / "project").resolve())

    def test_absolute_base(self):
        target = (self.directory / "other-project").resolve()
        self.write_config({"base_dir": str(target)})
        self.assertEqual(self.agent.load_base(), target)

    def test_utf8_bom_config(self):
        self.write_config({"base_dir": "project"}, encoding="utf-8-sig")
        self.assertEqual(self.agent.load_base(), self.agent.BASE)

    def test_missing_config_uses_dedicated_workspace(self):
        self.agent.CONFIG_FILE = self.directory / "missing.json"
        self.assertEqual(self.agent.load_base(), (Path.home() / "MuseWorkspace").resolve())

    def test_invalid_config_is_rejected(self):
        for value in ([], None, {}, {"base_dir": None}, {"base_dir": 1}, {"base_dir": " "}):
            with self.subTest(value=value):
                self.write_config(value)
                with self.assertRaises(ValueError):
                    self.agent.load_base()

    def test_malformed_json_is_rejected(self):
        self.config.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.agent.load_base()

    def test_configured_path_boundary(self):
        self.assertEqual(self.agent.safe_path("README.md"), self.agent.BASE / "README.md")
        for value in ("../outside", "..\\outside", str(self.directory / "outside")):
            with self.subTest(path=value):
                with self.assertRaises(ValueError):
                    self.agent.safe_path(value)

    def test_server_identifies_the_project(self):
        self.assertEqual(self.agent.Handler.server_version, "MuseWinAgent/2.0")

    def test_health_does_not_require_token(self):
        code, body = self.request("/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(body, {"ok": True, "base": str(self.agent.BASE)})

    def test_root_requires_token_but_has_no_route(self):
        code, body = self.request("/")
        self.assertEqual((code, body["error"]), (401, "bad token"))
        code, body = self.request("/", {"X-Token": self.agent.TOKEN})
        self.assertEqual((code, body["error"]), (404, "unknown api"))

    def test_authorization_header_is_not_supported(self):
        code, body = self.request("/api/ls", {"Authorization": "Bearer " + self.agent.TOKEN})
        self.assertEqual((code, body["error"]), (401, "bad token"))

    def test_authenticated_file_reads(self):
        (self.agent.BASE / "README.md").write_text("test content", encoding="utf-8")
        headers = {"X-Token": self.agent.TOKEN}
        code, body = self.request("/api/ls?path=", headers)
        self.assertEqual(code, 200)
        self.assertEqual([item["name"] for item in body["items"]], ["README.md"])
        code, body, content_type = self.request("/api/cat?path=README.md", headers)
        self.assertEqual((code, body, content_type), (200, b"test content", "application/octet-stream"))


class TrayConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.tree = ast.parse((ROOT / "src" / "tray_app.py").read_text(encoding="utf-8"))
        self.namespace = {
            "__file__": str(self.directory / "tray_app.py"),
            "Path": Path,
            "json": json,
            "sys": SimpleNamespace(executable=str(self.directory / "python.exe")),
        }

    def load_constants(self):
        body = []
        collecting = False
        for node in self.tree.body:
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)] if isinstance(node, ast.Assign) else []
            if "AGENT_DIR" in targets:
                collecting = True
            if collecting:
                body.append(node)
            if "NO_WINDOW" in targets:
                break
        exec(compile(ast.Module(body=body, type_ignores=[]), "tray-config", "exec"), self.namespace)

    def load_function(self, name):
        node = next(node for node in self.tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), "tray-function", "exec"), self.namespace)
        return self.namespace[name]

    def test_paths_are_discovered_without_private_defaults(self):
        self.load_constants()
        self.assertEqual(self.namespace["AGENT_DIR"], self.directory.resolve())
        self.assertEqual(self.namespace["PYW"], self.namespace["sys"].executable)
        self.assertEqual(self.namespace["URL"], "")

    def test_pythonw_and_local_url(self):
        (self.directory / "pythonw.exe").touch()
        (self.directory / "config.local.json").write_text(
            json.dumps({"base_dir": "project", "public_url": "https://example.com"}), encoding="utf-8-sig")
        self.load_constants()
        self.assertEqual(self.namespace["PYW"], str(self.directory / "pythonw.exe"))
        self.assertEqual(self.namespace["URL"], "https://example.com")

    def test_invalid_url_config(self):
        (self.directory / "config.local.json").write_text(json.dumps({"public_url": []}), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.load_constants()

    def test_missing_tunnel_config_does_not_launch_tunnel(self):
        self.load_constants()
        process = Mock()
        self.namespace.update(subprocess=process, agent_running=lambda: True, tunnel_running=Mock(), time=Mock())
        self.load_function("start_services")()
        process.Popen.assert_not_called()
        self.namespace["tunnel_running"].assert_not_called()

    def test_tray_image_is_generated_without_loading_an_asset(self):
        image_module = Mock()
        draw_module = Mock()
        pil = SimpleNamespace(Image=image_module, ImageDraw=draw_module)
        with patch.dict("sys.modules", {"PIL": pil}):
            result = self.load_function("create_tray_image")()
        image_module.new.assert_called_once_with("RGBA", (64, 64), (0, 0, 0, 0))
        image_module.open.assert_not_called()
        draw_module.Draw.assert_called_once_with(result)
        self.assertEqual(draw_module.Draw.return_value.ellipse.call_count, 2)
        draw_module.Draw.return_value.text.assert_not_called()
        self.assertIs(result, image_module.new.return_value)

    def test_process_controls_use_the_current_program_directory(self):
        self.load_constants()
        process = Mock()
        process.run.return_value = SimpleNamespace(returncode=0)
        self.namespace.update(subprocess=process, os=SimpleNamespace(environ={"KEEP_ENV": "value"}))
        for name in ("tunnel_running", "stop_services"):
            with self.subTest(function=name):
                process.reset_mock()
                self.load_function(name)()
                process.run.assert_called_once()
                args, kwargs = process.run.call_args
                self.assertEqual(kwargs["env"]["MUSE_AGENT_DIR"], str(self.directory.resolve()))
                self.assertEqual(kwargs["env"]["KEEP_ENV"], "value")
                self.assertIn("$env:MUSE_AGENT_DIR", args[0][-1])
                self.assertIn("OrdinalIgnoreCase", args[0][-1])

    def test_clipboard_argument_quotes_are_escaped_without_running_powershell(self):
        self.load_constants()
        process = Mock()
        self.namespace["subprocess"] = process
        self.load_function("copy_text")("https://example.com/a'b")
        command = process.run.call_args.args[0]
        self.assertEqual(command[-1], "Set-Clipboard -Value 'https://example.com/a''b'")


class LauncherTests(unittest.TestCase):
    def test_launchers_pass_an_absolute_script_path(self):
        for name in ("win_agent_start.bat", "一键启动助手.bat"):
            with self.subTest(script=name):
                text = (ROOT / "src" / name).read_text(encoding="utf-8")
                self.assertIn('"%~dp0win_agent.py"', text)

    def test_stop_script_uses_its_own_directory(self):
        text = (ROOT / "src" / "停止助手.bat").read_bytes().decode("gb18030")
        self.assertIn('set "MUSE_AGENT_DIR=%~dp0"', text)
        self.assertIn("$env:MUSE_AGENT_DIR", text)
        self.assertIn("OrdinalIgnoreCase", text)


if __name__ == "__main__":
    unittest.main()
