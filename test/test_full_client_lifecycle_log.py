"""Synthetic XML/files only. Packaged-Log4j acceptance uses LifecycleLogSmoke.java."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from full_client_lifecycle_log import (LogConfigError, MAX_XML_BYTES, derive_config, main,
                                       prepare_config, read_original)


ORIGINAL = b'''<?xml version="1.0" encoding="UTF-8"?>
<Configuration status="WARN" name="Synthetic" shutdownHook="disable">
  <Properties>
    <Property name="filename">cosmic-log</Property>
    <Property name="standard-pattern">%d{HH:mm:ss.SSS} [%t] %-5level %logger{2} - %msg%n</Property>
  </Properties>
  <!-- Ordinary appenders and startup rotation must be retained. -->
  <Appenders>
    <Console name="Console" target="SYSTEM_OUT"><PatternLayout pattern="${standard-pattern}"/></Console>
    <RollingFile name="File" fileName="logs/${filename}.log" filePattern="logs/old-%i.log">
      <PatternLayout><Pattern>${standard-pattern}</Pattern></PatternLayout>
      <Policies><OnStartupTriggeringPolicy minSize="0"/><SizeBasedTriggeringPolicy size="20 MB"/></Policies>
    </RollingFile>
    <File name="ChatFile" fileName="logs/chat.log"><PatternLayout pattern="%msg%n"/></File>
  </Appenders>
  <Loggers>
    <Root level="trace"><AppenderRef ref="File" level="debug"/><AppenderRef ref="Console" level="trace"/></Root>
    <Logger name="net.packet.logging" level="debug" additivity="false"><AppenderRef ref="Console"/><AppenderRef ref="File"/></Logger>
    <Logger name="server.ChatLogger" level="info" additivity="false"><AppenderRef ref="ChatFile"/></Logger>
  </Loggers>
</Configuration>'''


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def semantic(element):
    return (element.tag, dict(element.attrib), (element.text or "").strip(),
            [semantic(child) for child in element])


class LifecycleLogConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.original = self.root / "original.xml"
        self.original.write_bytes(ORIGINAL)
        self.output = self.root / "external.xml"
        self.log = self.root / "lifecycle.log"

    def derive(self, raw=ORIGINAL, log=None):
        return derive_config(raw, digest(raw), str(log or self.log), str(self.root))

    def prepare(self):
        return prepare_config(self.original, digest(ORIGINAL), self.output, self.log,
                              os.geteuid(), self.root)

    def test_only_one_nonrolling_appender_and_exact_existing_routes_are_added(self):
        raw = self.derive()
        self.assertEqual(raw, self.derive())
        root = ET.fromstring(raw)
        appender = root.find("Appenders/File[@name='Lifecycle']")
        self.assertEqual(appender.attrib, {"name": "Lifecycle", "fileName": str(self.log),
                                          "append": "true", "immediateFlush": "true"})
        self.assertEqual([child.tag for child in appender], ["PatternLayout"])
        self.assertEqual(semantic(appender[0]), semantic(root.find("Appenders/RollingFile/PatternLayout")))
        refs = [(logger.tag, logger.get("name"), ref.attrib) for logger in root.find("Loggers")
                for ref in logger.findall("AppenderRef") if ref.get("ref") == "Lifecycle"]
        self.assertEqual(refs, [("Root", None, {"ref": "Lifecycle", "level": "debug"}),
                                ("Logger", "net.packet.logging", {"ref": "Lifecycle"})])
        root.find("Appenders").remove(appender)
        for logger in root.find("Loggers"):
            for ref in list(logger):
                if ref.get("ref") == "Lifecycle":
                    logger.remove(ref)
        self.assertEqual(semantic(root), semantic(ET.fromstring(ORIGINAL)))
        self.assertIn(b"<!-- Ordinary appenders", raw)

    def test_exact_input_hash_required_before_transformation(self):
        for expected in ("0" * 64, "bad", None):
            with self.subTest(expected=expected), self.assertRaises(LogConfigError):
                derive_config(ORIGINAL, expected, str(self.log), str(self.root))

    def test_private_create_only_output_does_not_create_or_write_the_log(self):
        receipt = self.prepare()
        self.assertFalse(self.log.exists())
        self.assertEqual(receipt["original_sha256"], digest(ORIGINAL))
        self.assertEqual(receipt["output_sha256"], digest(self.output.read_bytes()))
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        self.assertEqual(self.output.stat().st_nlink, 1)
        self.assertFalse(receipt["log_created"])
        self.assertFalse(receipt["services_changed"])
        with self.assertRaisesRegex(LogConfigError, "output_exists"):
            self.prepare()
        self.assertEqual(digest(self.output.read_bytes()), receipt["output_sha256"])
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["external.xml", "original.xml"])

    def test_existing_log_prefix_is_untouched_and_generated_contract_is_append_only(self):
        prefix = b"synthetic older startup evidence\n"
        self.log.write_bytes(prefix)
        self.log.chmod(0o600)
        before = self.log.stat()
        self.prepare()
        after = self.log.stat()
        self.assertEqual(self.log.read_bytes(), prefix)
        self.assertEqual((before.st_ino, before.st_mtime_ns, before.st_ctime_ns),
                         (after.st_ino, after.st_mtime_ns, after.st_ctime_ns))
        generated = ET.parse(self.output).find("Appenders/File[@name='Lifecycle']")
        self.assertEqual(generated.get("append"), "true")
        self.assertIsNone(generated.find("Policies"))
        # Actual Log4j prefix preservation requires the separate Java fixture;
        # this assertion proves preparation itself never rewrites the log.

    def test_publication_exposes_only_complete_bytes_and_prepublication_failure_leaves_no_output(self):
        actual_link = os.link
        def inspect_link(source, target, **kwargs):
            self.assertFalse(self.output.exists())
            self.assertEqual((self.root / source).read_bytes(), self.derive())
            self.assertEqual(stat.S_IMODE((self.root / source).stat().st_mode), 0o600)
            return actual_link(source, target, **kwargs)
        with patch("full_client_lifecycle_log.os.link", side_effect=inspect_link):
            self.prepare()
        self.output.unlink()
        with patch("full_client_lifecycle_log.os.link", side_effect=OSError("synthetic sensitive detail")):
            with self.assertRaisesRegex(LogConfigError, "output_unavailable"):
                self.prepare()
        self.assertFalse(self.output.exists())
        self.assertEqual([path.name for path in self.root.iterdir()], ["original.xml"])

    def test_refuses_dtd_entities_processing_instructions_and_malformed_xml(self):
        for raw in (b'<!DOCTYPE Configuration [<!ENTITY x "boom">]><Configuration>&x;</Configuration>',
                    b'<!DOCTYPE Configuration SYSTEM "file:///synthetic-private"><Configuration/>',
                    ORIGINAL.replace(b"<Appenders>", b"<?unsafe arbitrary?><Appenders>"),
                    ORIGINAL.replace(b"</Configuration>", b""),
                    ORIGINAL.replace(b"<Root level=", b"<Root level='debug' level="),
                    ORIGINAL.replace(b"<Configuration ", b"<Configuration xmlns='unexpected' ")):
            with self.subTest(raw=raw[:50]), self.assertRaises(LogConfigError):
                self.derive(raw)

    def test_refuses_duplicate_conflicting_and_unsupported_routes(self):
        mutations = [
            ORIGINAL.replace(b"</Appenders>", b'<File name="Lifecycle" fileName="other"/></Appenders>'),
            ORIGINAL.replace(b"</Appenders>", b'<Console name="Console"/></Appenders>'),
            ORIGINAL.replace(b"</Loggers>", b'<Root/></Loggers>'),
            ORIGINAL.replace(b"</Loggers>", b'<Logger name="net.packet.logging"/></Loggers>'),
            ORIGINAL.replace(b"</Loggers>", b'<Logger name="extra"><AppenderRef ref="File"/></Logger></Loggers>'),
            ORIGINAL.replace(b'<AppenderRef ref="File" level="debug"/>', b'<AppenderRef ref="File"/><AppenderRef ref="File"/>'),
            ORIGINAL.replace(b'<AppenderRef ref="File" level="debug"/>', b'<AppenderRef ref="Lifecycle"/>'),
            ORIGINAL.replace(b'additivity="false"', b'additivity="true"', 1),
            ORIGINAL.replace(b'<Property name="filename">cosmic-log</Property>', b'<Property name="filename">a</Property><Property name="filename">b</Property>'),
            ORIGINAL.replace(b'<Configuration status=', b'<Configuration monitorInterval="1" status='),
            ORIGINAL.replace(b'ref="Console"', b'ref="missing"'),
        ]
        for raw in mutations:
            with self.subTest(raw=digest(raw)), self.assertRaises(LogConfigError):
                self.derive(raw)

    def test_refuses_collision_with_ordinary_relative_or_property_expanded_log(self):
        with self.assertRaisesRegex(LogConfigError, "conflicting_lifecycle_appender"):
            self.derive(log=self.root / "logs" / "cosmic-log.log")
        for value in (b"${env:ARBITRARY}", b"${unknown}", b"${filename}"):
            raw = ORIGINAL.replace(b">cosmic-log</Property>", b">" + value + b"</Property>")
            with self.subTest(value=value), self.assertRaisesRegex(LogConfigError, "unsupported_log_path"):
                self.derive(raw)

    def test_output_cannot_create_an_ordinary_active_log(self):
        # Put archives elsewhere so this specifically exercises active paths.
        raw = ORIGINAL.replace(b'filePattern="logs/old-%i.log"', b'filePattern="archives/old-%i.log"')
        self.original.write_bytes(raw)
        (self.root / "logs").mkdir(mode=0o700)
        for name in ("cosmic-log.log", "chat.log"):
            self.output = self.root / "logs" / name
            with self.subTest(name=name), patch("full_client_lifecycle_log._publish") as publish:
                with self.assertRaisesRegex(LogConfigError, "conflicting_lifecycle_appender"):
                    prepare_config(self.original, digest(raw), self.output, self.log, os.geteuid(), self.root)
                publish.assert_not_called()
            self.assertFalse(self.output.exists())
            self.assertFalse(self.log.exists())
        self.assertEqual(self.original.read_bytes(), raw)

    def test_output_cannot_alias_a_missing_ordinary_active_log(self):
        logs = self.root / "logs"
        logs.mkdir(mode=0o700)
        ordinary = logs / "cosmic-log.log"
        ordinary.symlink_to(self.output)
        with self.assertRaisesRegex(LogConfigError, "conflicting_lifecycle_appender"):
            self.prepare()
        self.assertTrue(ordinary.is_symlink())
        self.assertFalse(self.output.exists())
        self.assertFalse(self.log.exists())

    def test_output_and_lifecycle_log_must_stay_outside_archive_tree(self):
        archives = self.root / "logs"
        archives.mkdir(mode=0o700)
        (archives / "nested").mkdir(mode=0o700)
        for relative in ("old-1.log", "unrelated.xml", "nested/evidence.log"):
            destination = archives / relative
            with self.subTest(role="log", relative=relative):
                with self.assertRaisesRegex(LogConfigError, "conflicting_lifecycle_appender"):
                    self.derive(log=destination)
            self.output = destination
            with self.subTest(role="output", relative=relative):
                with self.assertRaisesRegex(LogConfigError, "conflicting_lifecycle_appender"):
                    self.prepare()
            self.assertFalse(destination.exists())
        self.assertFalse(self.log.exists())
        self.assertEqual(self.original.read_bytes(), ORIGINAL)

    def test_archive_directory_properties_are_expanded_before_collision_check(self):
        raw = ORIGINAL.replace(b"<Properties>", b'<Properties><Property name="archive">private/archive</Property>')
        raw = raw.replace(b'filePattern="logs/old-%i.log"', b'filePattern="${archive}/old-%d{yyyy-MM-dd}-%i.log"')
        with self.assertRaisesRegex(LogConfigError, "conflicting_lifecycle_appender"):
            self.derive(raw, self.root / "private" / "archive" / "evidence.log")
        # A separate sibling directory is supported without changing the pattern.
        self.assertIn(b'filePattern="${archive}/old-%d{yyyy-MM-dd}-%i.log"', self.derive(raw))

    def test_real_deferred_date_archive_pattern_is_preserved_without_current_date_substitution(self):
        pattern = b"logs/$${date:yyyy-MM}/$${date:yyyy-MM-dd}/${filename}-%d{yyyy-MM-dd_HH-mm-ss}-%i.log"
        raw = ORIGINAL.replace(b"logs/old-%i.log", pattern)
        generated = self.derive(raw)
        self.assertEqual(ET.fromstring(generated).find("Appenders/RollingFile").get("filePattern"),
                         pattern.decode())
        self.assertEqual(generated, self.derive(raw))
        # Declared literal properties can supply the same fixed, bounded tokens.
        with_property = raw.replace(b"<Properties>", b'<Properties><Property name="month">$${date:yyyy-MM}</Property>')
        with_property = with_property.replace(b"logs/$${date:yyyy-MM}/", b"logs/${month}/")
        self.assertIn(b'filePattern="logs/${month}/', self.derive(with_property))

    def test_deferred_date_pattern_reserves_entire_static_archive_tree_for_both_destinations(self):
        pattern = b"logs/$${date:yyyy-MM}/$${date:yyyy-MM-dd}/${filename}-%d{yyyy-MM-dd_HH-mm-ss}-%i.log"
        raw = ORIGINAL.replace(b"logs/old-%i.log", pattern)
        self.original.write_bytes(raw)
        for relative in ("evidence.log", "2099-12/2099-12-31/evidence.log", "other/future/config.xml"):
            destination = self.root / "logs" / relative
            with self.subTest(role="log", relative=relative), self.assertRaisesRegex(LogConfigError, "conflicting_lifecycle_appender"):
                self.derive(raw, destination)
            with self.subTest(role="output", relative=relative), self.assertRaisesRegex(LogConfigError, "conflicting_lifecycle_appender"):
                prepare_config(self.original, digest(raw), destination, self.log, os.geteuid(), self.root)
            self.assertFalse(destination.exists())
        self.assertFalse(self.log.exists())
        self.assertEqual(self.original.read_bytes(), raw)

    def test_deferred_archive_dates_refuse_escaping_arbitrary_lookups_and_unbounded_prefixes(self):
        patterns = (
            b"$${date:yyyy-MM}/old-%i.log", b"/$${date:yyyy-MM}/old-%i.log",
            b"./$${date:yyyy-MM}/old-%i.log", b"logs/../$${date:yyyy-MM}/old-%i.log",
            b"logs/$${date:yyyy/MM}/old-%i.log", b"logs/$${date:yyyy-MM}/../old-%i.log",
            b"logs/$$${date:yyyy-MM}/old-%i.log", b"logs/$${env:ARCHIVES}/old-%i.log",
            b"logs/$${filename}/old-%i.log", b"logs/${date:yyyy-MM}/old-%i.log",
            b"logs/prefix-$${date:yyyy-MM}/old-%i.log", b"logs/$${date:yyyy-MM}/%d{yyyy-MM}/old-%i.log",
            b"logs/$${date:yyyy-MM}/$${date:yyyy-MM}/$${date:yyyy-MM}/old-%i.log",
            b"logs/$${date:yyyy-MM}-${env:PRIVATE}/old-%i.log", b"logs/old-$${date:yyyy-MM}-%i.log",
        )
        for pattern in patterns:
            raw = ORIGINAL.replace(b"logs/old-%i.log", pattern)
            with self.subTest(pattern=pattern), self.assertRaisesRegex(LogConfigError, "unsupported_log_path"):
                self.derive(raw)

    def test_unbounded_archive_directories_and_parent_traversal_are_refused(self):
        for pattern in (b"logs/%d{yyyy-MM}/old-%i.log", b"logs/../archives/old-%i.log",
                        b"${env:ARCHIVES}/old-%i.log", b""):
            raw = ORIGINAL.replace(b'filePattern="logs/old-%i.log"', b'filePattern="' + pattern + b'"')
            with self.subTest(pattern=pattern), self.assertRaisesRegex(LogConfigError, "unsupported_log_path"):
                self.derive(raw)
        raw = ORIGINAL.replace(b'fileName="logs/${filename}.log"', b'fileName="logs/../cosmic.log"')
        with self.assertRaisesRegex(LogConfigError, "unsupported_log_path"):
            self.derive(raw)

    def test_archive_directory_alias_cannot_reach_output_or_lifecycle_log(self):
        # No active filename equals either destination; the archive directory
        # alias alone would let a future rollover enter the private directory.
        (self.root / "logs").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(LogConfigError, "conflicting_lifecycle_appender"):
            self.prepare()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.log.exists())
        self.assertEqual(self.original.read_bytes(), ORIGINAL)

    def test_rejects_size_depth_and_path_substitution(self):
        for raw in (b"x" * (MAX_XML_BYTES + 1), b"<Configuration>" + b"<x>" * 34 + b"</x>" * 34 + b"</Configuration>"):
            with self.subTest(size=len(raw)), self.assertRaisesRegex(LogConfigError, "xml_limit"):
                self.derive(raw)
        for path in ("relative.log", str(self.root / "${env:PRIVATE}"), str(self.root) + "/../bad.log"):
            with self.subTest(path=path), self.assertRaisesRegex(LogConfigError, "invalid_absolute_path"):
                derive_config(ORIGINAL, digest(ORIGINAL), path, str(self.root))

    def test_refuses_actual_alias_to_existing_ordinary_log(self):
        logs = self.root / "logs"
        logs.mkdir(mode=0o700)
        self.log.write_bytes(b"existing evidence")
        self.log.chmod(0o600)
        (logs / "cosmic-log.log").symlink_to(self.log)
        with self.assertRaisesRegex(LogConfigError, "conflicting_lifecycle_appender"):
            self.prepare()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.log.read_bytes(), b"existing evidence")

    def test_refuses_nonprivate_or_symlink_output_and_log_paths(self):
        self.log.write_bytes(b"sentinel")
        self.log.chmod(0o644)
        with self.assertRaisesRegex(LogConfigError, "log_path_not_private"):
            self.prepare()
        self.assertFalse(self.output.exists())
        self.log.unlink()
        self.log.symlink_to(self.original)
        with self.assertRaisesRegex(LogConfigError, "log_path_not_private"):
            self.prepare()
        self.log.unlink()
        self.output.symlink_to(self.original)
        with self.assertRaisesRegex(LogConfigError, "output_exists"):
            self.prepare()
        self.assertEqual(self.original.read_bytes(), ORIGINAL)
        self.output.unlink()
        self.root.chmod(0o755)
        try:
            with self.assertRaisesRegex(LogConfigError, "private_parent_required"):
                self.prepare()
        finally:
            self.root.chmod(0o700)

    def test_original_symlink_and_replacement_are_refused(self):
        alias = self.root / "alias.xml"
        alias.symlink_to(self.original)
        with self.assertRaisesRegex(LogConfigError, "original_unavailable"):
            read_original(alias)
        actual_read = os.read
        changed = False
        def replacing_read(fd, count):
            nonlocal changed
            raw = actual_read(fd, count)
            if not changed:
                changed = True
                replacement = self.root / "replacement.xml"
                replacement.write_bytes(ORIGINAL)
                replacement.replace(self.original)
            return raw
        with patch("full_client_lifecycle_log.os.read", side_effect=replacing_read):
            with self.assertRaisesRegex(LogConfigError, "original_changed"):
                read_original(self.original)

    def test_cli_reports_only_fixed_code_on_bad_input(self):
        self.original.write_bytes(b"synthetic-sensitive invalid XML")
        output = io.StringIO()
        with patch("sys.stdout", output):
            code = main(["--original", str(self.original), "--original-sha256", digest(ORIGINAL),
                         "--output", str(self.output), "--log-path", str(self.log),
                         "--log-owner-uid", str(os.geteuid()), "--working-directory", str(self.root)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), {"ok": False, "error": "original_hash_mismatch"})
        self.assertFalse(self.output.exists())
        self.assertNotIn("synthetic-sensitive", output.getvalue())


if __name__ == "__main__":
    unittest.main()
