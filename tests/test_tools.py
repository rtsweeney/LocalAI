"""Tests for the audiobook maker and the model-fit checker. No GPU or internet needed."""
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import audiobook as ab  # noqa: E402
import fit  # noqa: E402


class FakeVoice(BaseHTTPRequestHandler):
    spoken = []
    fail_on = None

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if FakeVoice.fail_on and FakeVoice.fail_on in body["input"]:
            return self.send_error(500)
        FakeVoice.spoken.append(body)
        data = b"<" + body["input"].encode() + b">"
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_epub(path, encrypted=False):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml",
                   '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf",
                   '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
                   '<item id="c2" href="text/two.xhtml"/><item id="c1" href="text/one%20a.xhtml"/>'
                   '<item id="cover" href="cover.xhtml"/></manifest>'
                   '<spine><itemref idref="cover"/><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
        z.writestr("OEBPS/cover.xhtml", "<html><body><p>Cover</p></body></html>")
        z.writestr("OEBPS/text/one a.xhtml", "<html><head><title>x</title><style>p{}</style></head><body>"
                   "<h1>The Start: Part/One?</h1><p>" + "First chapter sentence. " * 20 + "</p></body></html>")
        z.writestr("OEBPS/text/two.xhtml", "<html><body><h2>The End</h2><p>"
                   + "Second chapter sentence. " * 20 + "</p></body></html>")
        if encrypted:
            z.writestr("META-INF/encryption.xml", "<encryption><EncryptedData/></encryption>")


class AudiobookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeVoice)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeVoice.spoken, FakeVoice.fail_on = [], None
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_epub_chapters_come_out_in_reading_order_one_mp3_each(self):
        book = self.dir / "book.epub"
        make_epub(book)
        ab.main([str(book), "--url", self.url, "--voice", "bm_george"])
        files = sorted(p.name for p in (self.dir / "book (audiobook)").iterdir())
        self.assertEqual(files, ["001 The Start PartOne.mp3", "002 The End.mp3"])  # cover skipped
        self.assertTrue(all(b["voice"] == "bm_george" and b["model"] == "kokoro" for b in FakeVoice.spoken))
        first = (self.dir / "book (audiobook)" / files[0]).read_bytes().decode()
        self.assertIn("First chapter sentence.", first)
        self.assertNotIn("p{}", first)  # style sheets are not read aloud

    def test_rerun_skips_finished_chapters_and_a_failure_leaves_no_half_mp3(self):
        book = self.dir / "book.epub"
        make_epub(book)
        FakeVoice.fail_on = "Second chapter"
        with self.assertRaises(SystemExit):
            ab.main([str(book), "--url", self.url])
        out = self.dir / "book (audiobook)"
        self.assertEqual([p.name for p in out.glob("*.mp3")], ["001 The Start PartOne.mp3"])
        FakeVoice.fail_on, FakeVoice.spoken = None, []
        ab.main([str(book), "--url", self.url])
        self.assertEqual(len(list(out.glob("*.mp3"))), 2)
        self.assertTrue(all("First chapter" not in b["input"] for b in FakeVoice.spoken))

    def test_protected_epub_is_refused_with_a_reason(self):
        book = self.dir / "drm.epub"
        make_epub(book, encrypted=True)
        with self.assertRaises(SystemExit) as e:
            ab.main([str(book), "--url", self.url])
        self.assertIn("copy-protected", str(e.exception))

    def test_txt_splits_on_chapter_headings(self):
        book = self.dir / "story.txt"
        book.write_text("Chapter 1\nHello there. " * 1 + "\nChapter 2\nGoodbye now.", encoding="utf-8")
        self.assertEqual([t for t, _ in ab.read_txt(book)], ["Chapter 1", "Chapter 2"])

    def test_chunks_keep_every_word_and_respect_the_size_limit(self):
        text = ("A short one. " * 30) + ("word " * 400) + "\nThe last line!"
        parts = ab.chunks(text, 200)
        self.assertTrue(all(len(p) <= 200 for p in parts))
        self.assertEqual(" ".join(parts).split(), text.split())


class FitTest(unittest.TestCase):
    FILES = [
        {"type": "file", "path": "m-Q4_K_M.gguf", "size": 10 * fit.GB},
        {"type": "file", "path": "m-Q8_0.gguf", "lfs": {"size": 20 * fit.GB}, "size": 135},
        {"type": "file", "path": "big-Q6_K-00001-of-00002.gguf", "size": 6 * fit.GB},
        {"type": "file", "path": "big-Q6_K-00002-of-00002.gguf", "size": 6 * fit.GB},
        {"type": "file", "path": "m-mmproj-F16.gguf", "size": fit.GB},
        {"type": "file", "path": "README.md", "size": 10},
        {"type": "directory", "path": "x.gguf"},
    ]

    def test_variants_group_split_files_and_ignore_addons(self):
        v = fit.variants(self.FILES)
        self.assertEqual([(x["quant"], round(x["bytes"] / fit.GB), x["parts"]) for x in v],
                         [("Q4_K_M", 10, 1), ("Q6_K", 12, 2), ("Q8_0", 20, 1)])

    def test_verdicts(self):
        self.assertEqual(fit.verdict(fit.need_gb(10 * fit.GB, 8192, 1.0), 16), "FITS")      # 11.5
        self.assertEqual(fit.verdict(fit.need_gb(14 * fit.GB, 8192, 1.0), 16), "FITS")      # 15.5
        self.assertEqual(fit.verdict(fit.need_gb(14 * fit.GB, 16384, 1.0), 16), "TIGHT")    # 16.0
        self.assertEqual(fit.verdict(fit.need_gb(14 * fit.GB, 32768, 1.0), 16), "TOO BIG")  # 17.0
        self.assertEqual([fit.bits(q) for q in ("Q4_K_M", "IQ3_XXS", "F16", "?")], [4, 3, 16, 0])


if __name__ == "__main__":
    unittest.main()
