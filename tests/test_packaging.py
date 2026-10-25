import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_game_vpk as pack


class PackagingTests(unittest.TestCase):
    def test_https_bundle_is_packaged_outside_game_love(self):
        data = BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            pack.write_network_assets(archive)
        with zipfile.ZipFile(BytesIO(data.getvalue())) as archive:
            bundle = archive.read("cacert.pem")
            self.assertEqual(bundle, (pack.HERE / "native/cacert.pem").read_bytes())
            self.assertGreater(bundle.count(b"-----BEGIN CERTIFICATE-----"), 50)
            self.assertIn(b"Mozilla", archive.read("CA-LICENSE"))
            self.assertIn(b"OpenSSL", archive.read("NETWORK-LICENSES.txt"))

    def test_new_game_manifests_are_required(self):
        for game in ('emerald', 'ruby', 'sapphire'):
            self.assertIn(f'tools/rom_manifest_{game}.json', pack.REQUIRED)

    def test_release_exclusions_and_runtime_shim(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp)
            for name in pack.REQUIRED:
                if name == 'conf_engine.lua':
                    name = 'conf.lua'
                path = engine / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('return {}')
            for name in ('data/generated/leak.lua', 'assets/generated/leak.rgba',
                         'assets/design.psd', 'assets/.DS_Store'):
                path = engine / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'exclude')
            data, count = pack.build_love(engine, '22050', {})
            with zipfile.ZipFile(BytesIO(data)) as archive:
                self.assertEqual(count, len(archive.namelist()))
                self.assertTrue(set(pack.REQUIRED).issubset(archive.namelist()))
                self.assertFalse(any(n.endswith(('.psd', '.DS_Store')) or
                                     n.startswith(pack.EXCLUDE_PREFIXES)
                                     for n in archive.namelist()))
                shim = archive.read('conf.lua').decode()
                self.assertIn('local AUDIO_RATE = "22050"', shim)
                self.assertIn('t.window.width = 960', shim)
                self.assertNotIn('@AUDIO_RATE@', shim)

    def test_gba_dump_in_asset_tree_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp)
            for name in pack.REQUIRED:
                if name == 'conf_engine.lua':
                    name = 'conf.lua'
                path = engine / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('return {}')
            path = engine / 'assets/private.gba'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
            with self.assertRaisesRegex(SystemExit, 'ROM data'):
                pack.build_love(engine, '22050', {})


if __name__ == '__main__':
    unittest.main()
