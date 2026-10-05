"""Test de echte configuratie; de bestaande regressies gebruiken een config-mock."""
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import bcrypt  # Houd de native module geladen tijdens de config-isolatie van regressietests.
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
APP_MODULES = ("config", "auth", "bestanden", "ai_docent", "storingen", "ui_beheer", "ui_leerling")


class StartupTests(unittest.TestCase):
    def setUp(self):
        original = {name: sys.modules.get(name) for name in APP_MODULES}
        def restore():
            for name, module in original.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        self.addCleanup(restore)
        for name in APP_MODULES:
            sys.modules.pop(name, None)
        self.config = importlib.import_module("config")
        self.config._maak_ai_client.clear()
        self.config._maak_supabase_client.clear()
        self.addCleanup(self.config._maak_ai_client.clear)
        self.addCleanup(self.config._maak_supabase_client.clear)

    def app(self):
        app = AppTest.from_file(str(ROOT / "main.py"), default_timeout=15)
        # Een lege secrets-configuratie zonder een lokaal secrets-bestand nodig te hebben.
        app.secrets["TEST"] = "offline"
        return app

    def test_login_start_zonder_secrets_of_clients(self):
        with patch.object(self.config, "_maak_ai_client") as ai, \
             patch.object(self.config, "_maak_supabase_client") as db, \
             patch.object(self.config, "haal_wikimedia_potd_url_op", return_value=""):
            app = self.app().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Huiswerkcontrole" in title.value for title in app.title))
            self.assertTrue(any(b.label == "Inloggen" for b in app.button))
            self.assertTrue(any(b.label == "Start als Gast" for b in app.button))
            app.run()
            self.assertFalse(app.exception)
            ai.assert_not_called()
            db.assert_not_called()

    def test_login_start_ook_bij_ongeldige_api_instellingen(self):
        with patch.object(self.config, "_maak_ai_client", side_effect=ValueError("ongeldig")) as ai, \
             patch.object(self.config, "_maak_supabase_client", side_effect=ValueError("ongeldig")) as db, \
             patch.object(self.config, "haal_wikimedia_potd_url_op", return_value=""):
            app = self.app()
            app.secrets["GEMINI_API_KEY"] = "ongeldig"
            app.secrets["SUPABASE_URL"] = "ongeldig"
            app.secrets["SUPABASE_KEY"] = "ongeldig"
            app.run()
            self.assertFalse(app.exception)
            ai.assert_not_called()
            db.assert_not_called()

    def test_gast_zonder_database_toont_melding_in_plaats_van_crash(self):
        with patch.object(self.config, "haal_wikimedia_potd_url_op", return_value=""):
            app = self.app().run()
            # Het gastformulier heeft bewust dezelfde naamvraag als de registratie.
            gast = next(t for t in app.tabs if t.label == "🚀 Gasttoegang")
            gast.text_input[0].set_value("Testgast")
            next(b for b in app.button if b.label == "Start als Gast").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("SUPABASE_URL" in e.value for e in app.error))

    def test_database_is_onafhankelijk_van_gemini(self):
        with patch.object(self.config.st, "secrets", {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_KEY": "test"}), \
             patch.object(self.config, "_maak_supabase_client") as db, \
             patch.object(self.config, "_maak_ai_client") as ai:
            self.config.supabase.table("gebruikers")
            db.assert_called_once_with("https://test.supabase.co", "test")
            db.return_value.table.assert_called_once_with("gebruikers")
            ai.assert_not_called()

    def test_ai_client_wordt_hergebruikt(self):
        with patch.object(self.config.st, "secrets", {"GEMINI_API_KEY": "test"}), \
             patch.object(self.config.genai, "Client") as constructor:
            eerste = self.config.get_ai_client()
            tweede = self.config.get_ai_client()
            self.assertIs(eerste, tweede)
            constructor.assert_called_once_with(api_key="test")

    def test_codespaces_start_bestaand_bestand(self):
        config = json.loads((ROOT / ".devcontainer/devcontainer.json").read_text())
        command = config["postAttachCommand"]["server"]
        self.assertEqual(command, "streamlit run main.py")
        self.assertTrue((ROOT / "main.py").is_file())
