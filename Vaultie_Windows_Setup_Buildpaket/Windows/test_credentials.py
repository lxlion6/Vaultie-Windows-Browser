"""Tests for local Windows login vault and origin isolation."""
import os
import tempfile
import unittest
from pathlib import Path
from credentials import CredentialVault, secure_origin


class OriginTests(unittest.TestCase):
    def test_https_exact_origin(self):
        self.assertEqual(secure_origin("https://Example.COM/login?a=1"),
                         "https://example.com")
        self.assertEqual(secure_origin("https://example.com:8443/path"),
                         "https://example.com:8443")

    def test_reject_insecure_and_invalid(self):
        for url in ("http://example.com", "file:///file", "about:blank",
                    "https://user:secret@example.com", "javascript:alert(1)"):
            self.assertIsNone(secure_origin(url))


@unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
class VaultTests(unittest.TestCase):
    def test_encrypt_roundtrip_and_remove(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "vault.dat"
            vault = CredentialVault(path)
            vault.save("https://example.com", "name@example.com", "not-plaintext-password")
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("not-plaintext-password", raw)
            reopened = CredentialVault(path)
            self.assertEqual(reopened.get("https://example.com"),
                             {"username": "name@example.com",
                              "password": "not-plaintext-password"})
            self.assertIsNone(reopened.get("https://other.example.com"))
            reopened.remove("https://example.com")
            self.assertIsNone(CredentialVault(path).get("https://example.com"))

    def test_refuse_insecure_site(self):
        with tempfile.TemporaryDirectory() as folder:
            vault = CredentialVault(Path(folder) / "vault.dat")
            with self.assertRaises(ValueError):
                vault.save("http://example.com", "user", "password")


if __name__ == "__main__":
    unittest.main()
