"""Isolated JPEG two-fragment prototype using decoded synthetic fixtures.

Only alignment-derived cut positions and caller-provided candidate ranges enter
search. Fixture offsets and SHA-256 remain test-oracle data checked afterward.
"""
from __future__ import annotations
from dataclasses import dataclass
from io import BytesIO
import hashlib
import os
import random
import sys
import time
import unittest
import warnings
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.formats.primary import valid_jpeg

ALIGNMENT = 4096
PAIR_LIMIT = 64
READ_LIMIT = 8 * 1024 * 1024
CANDIDATE_LIMIT = 2 * 1024 * 1024
TIME_LIMIT = 2.0
MEMORY_LIMIT = 16 * 1024 * 1024

@dataclass(frozen=True)
class JpegResult:
    hypotheses: tuple[tuple[int, int, bytes], ...]
    cut_points_considered: int
    pairs: int
    bytes_read: int
    elapsed: float
    peak_buffer_estimate: int
    stop_reason: str
    safe_marker_rejections: int = 0
    decoder_calls: int = 0
    decoder_warning_candidates: int = 0
    unique_bytes_read: int = 0
    eoi_candidate_checks: int = 0
    decoder_errors: int = 0

    @property
    def classification(self):
        if self.stop_reason == "ambiguous": return "ambiguous"
        if self.stop_reason == "search_exhausted":
            return "structural_hypothesis" if self.hypotheses else "rejected"
        if self.stop_reason.startswith("error:"): return "error"
        return "limit_reached"


def jpeg_fixture(*, width=128, height=128, progressive=False, quality=82, seed=7, restart_blocks=None):
    rng = random.Random(seed)
    pixels = bytes(rng.randrange(256) for _ in range(width * height * 3))
    image = Image.frombytes("RGB", (width, height), pixels)
    output = BytesIO()
    options = dict(format="JPEG", quality=quality, progressive=progressive,
                   optimize=False, subsampling=0)
    if restart_blocks is not None:
        options["restart_marker_blocks"] = restart_blocks
    image.save(output, **options)
    return output.getvalue()


def similar_jpeg_fixtures(*, progressive=False, quality=84, restart_blocks=None):
    width=height=256
    common=bytearray()
    alternative=bytearray()
    for y in range(height):
        for x in range(width):
            pixel=((x*17+y*13)%256,(x*7+y*23)%256,(x*29+y*3)%256)
            other=pixel if y<200 else ((pixel[0]+61)%256,(pixel[1]+97)%256,(pixel[2]+137)%256)
            common.extend(pixel); alternative.extend(other)
    def encode(raw):
        image=Image.frombytes("RGB",(width,height),bytes(raw)); output=BytesIO()
        options=dict(format="JPEG",quality=quality,progressive=progressive,
            optimize=False,subsampling=0)
        if restart_blocks is not None: options["restart_marker_blocks"]=restart_blocks
        image.save(output,**options); return output.getvalue()
    return encode(common),encode(alternative)


def decode_jpeg(data):
    with Image.open(BytesIO(data)) as image:
        image.load()
        return image.format, image.size, image.mode


def decode_jpeg_with_warnings(data):
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        decoded = decode_jpeg(data)
    return decoded, tuple(str(item.message) for item in observed)


def strict_jpeg_scan(data: bytes) -> tuple[bool, str, int, int]:
    """Validate marker framing, stuffed bytes, scan boundaries and RST order."""
    if not data.startswith(b"\xff\xd8"):
        return False, "soi", 0, 0
    pos = 2; frame = ""; scans = restart_count = 0; restart_interval = 0
    expected_restart = 0
    while pos < len(data):
        if data[pos] != 0xff:
            return False, "marker_prefix", scans, restart_count
        marker_start = pos
        while pos < len(data) and data[pos] == 0xff:
            pos += 1
        if pos >= len(data):
            return False, "truncated_marker", scans, restart_count
        marker = data[pos]; pos += 1
        if marker in (0x00, 0xd8) or 0xd0 <= marker <= 0xd7:
            return False, "standalone_marker_outside_scan", scans, restart_count
        if marker == 0xd9:
            if scans == 0 or pos != len(data):
                return False, "eoi_or_trailing_data", scans, restart_count
            return True, frame, scans, restart_count
        if marker == 0x01:  # TEM has no length field.
            continue
        if pos + 2 > len(data):
            return False, "truncated_segment_length", scans, restart_count
        length = int.from_bytes(data[pos:pos + 2], "big")
        if length < 2 or pos + length > len(data):
            return False, "segment_length", scans, restart_count
        segment_end = pos + length
        if marker in (0xc0, 0xc2):
            components = data[pos + 7] if length >= 8 else 0
            if (length != 8 + components * 3 or components == 0
                    or int.from_bytes(data[pos + 3:pos + 5], "big") == 0
                    or int.from_bytes(data[pos + 5:pos + 7], "big") == 0):
                return False, "frame_header", scans, restart_count
            width=int.from_bytes(data[pos+5:pos+7],"big")
            height=int.from_bytes(data[pos+3:pos+5],"big")
            if width*height>1_048_576:
                return False,"decoded_pixel_limit",scans,restart_count
            if frame:
                return False, "multiple_frames", scans, restart_count
            frame = "baseline" if marker == 0xc0 else "progressive"
        if marker == 0xdd:
            if length != 4:
                return False, "restart_interval_segment", scans, restart_count
            restart_interval = int.from_bytes(data[pos + 2:pos + 4], "big")
        if marker != 0xda:
            pos = segment_end
            continue
        if not frame:
            return False, "scan_before_frame", scans, restart_count
        components = data[pos + 2] if length >= 3 else 0
        if components == 0 or length != 6 + components * 2:
            return False, "scan_header", scans, restart_count
        pos = segment_end; scan_bytes = 0; expected_restart = 0
        while pos < len(data):
            entropy_marker_start = data.find(b"\xff",pos)
            if entropy_marker_start < 0:
                return False, "missing_eoi", scans, restart_count
            scan_bytes += entropy_marker_start-pos
            pos=entropy_marker_start
            pos += 1
            while pos < len(data) and data[pos] == 0xff:
                pos += 1
            if pos >= len(data):
                return False, "truncated_entropy_marker", scans, restart_count
            code = data[pos]
            if code == 0x00:  # byte-stuffed FF in entropy-coded data
                scan_bytes += pos - entropy_marker_start + 1; pos += 1; continue
            if 0xd0 <= code <= 0xd7:
                if restart_interval == 0 or code != 0xd0 + expected_restart:
                    return False, "restart_sequence", scans, restart_count
                expected_restart = (expected_restart + 1) % 8
                restart_count += 1; scan_bytes += pos - entropy_marker_start + 1
                pos += 1; continue
            pos = entropy_marker_start
            break
        if scan_bytes == 0:
            return False, "empty_scan", scans, restart_count
        scans += 1
    return False, "missing_eoi", scans, restart_count


def marker_summary(data):
    """Report SOF mode, scan count, DRI, RST count, and EOI from real JPEG bytes."""
    sof = None; scans = 0; dri = None; restarts = 0; pos = 2
    while pos < len(data):
        if data[pos] != 0xff: pos += 1; continue
        while pos < len(data) and data[pos] == 0xff: pos += 1
        if pos >= len(data): break
        marker=data[pos]; pos += 1
        if marker == 0x00: continue
        if 0xd0 <= marker <= 0xd7: restarts += 1; continue
        if marker == 0xd9: break
        if marker == 0xd8 or marker == 0x01: continue
        if pos+2 > len(data): break
        length=int.from_bytes(data[pos:pos+2],"big")
        if length < 2 or pos+length > len(data): break
        if marker in (0xc0,0xc2): sof="baseline" if marker==0xc0 else "progressive"
        if marker == 0xdd: dri=int.from_bytes(data[pos+2:pos+4],"big")
        if marker == 0xda:
            scans += 1; pos += length
            while pos < len(data):
                if data[pos] != 0xff: pos += 1; continue
                marker_start=pos; pos += 1
                while pos < len(data) and data[pos] == 0xff: pos += 1
                if pos == len(data): break
                code=data[pos]
                if code == 0x00: pos += 1; continue
                if 0xd0 <= code <= 0xd7: restarts += 1; pos += 1; continue
                pos=marker_start; break
            continue
        pos += length
    return {"frame":sof,"scans":scans,"restart_interval":dri,"restart_markers":restarts,"eoi":data.endswith(b"\xff\xd9")}


def _carve_contiguous_jpeg(data):
    class Reader:
        size=len(data)
        def read_at(self,offset,size): return data[offset:offset+size]
    carver=RawContentCarver(Reader(),max_file_bytes=max(1,len(data)))
    return carver._read_jpeg(0,len(data),max(1,len(data)*2))[0]


class JpegFragmentDiscovery:
    """Enumerate alignment-derived cut and continuation hypotheses under budgets."""
    def __init__(self, source, *, signature_offset, candidate_ranges, alignment=ALIGNMENT,
                 max_pairs=PAIR_LIMIT, max_reads=READ_LIMIT, max_candidate=CANDIDATE_LIMIT,
                 max_seconds=TIME_LIMIT, max_memory=MEMORY_LIMIT, monotonic=time.monotonic):
        self.source=source; self.sig=signature_offset; self.ranges=candidate_ranges
        self.alignment=alignment; self.max_pairs=max_pairs; self.max_reads=max_reads
        self.max_candidate=max_candidate; self.max_seconds=max_seconds; self.max_memory=max_memory; self.clock=monotonic

    def run(self):
        started=self.clock(); reads=0; pairs=0; peak=0; found=[]; reason="search_exhausted"; cut_points_considered=0
        decoder_calls=decoder_warnings=decoder_errors=eoi_checks=0; source_ranges=[]
        try:
            # The cut search is geometric and bounded; it does not receive a
            # fixture cut. Marker/decoder checks qualify candidates afterward.
            cut_end=min(self.source.size, self.sig+self.max_candidate)
            cuts=list(range(self.sig+self.alignment, cut_end, self.alignment))
            cut_points_considered=len(cuts)
            starts=[]
            for lo,hi in self.ranges:
                pos=((lo+self.alignment-1)//self.alignment)*self.alignment
                while pos<hi: starts.append(pos); pos+=self.alignment
            for cut in cuts:
                for continuation in starts:
                    if pairs>=self.max_pairs: reason="combination_limit"; raise StopIteration
                    if self.clock()-started>=self.max_seconds: reason="time_limit"; raise StopIteration
                    pairs+=1
                    prefix_size=cut-self.sig
                    if prefix_size >= self.max_candidate: reason="candidate_size_limit"; raise StopIteration
                    available_tail=self.source.size-continuation
                    tail_size=min(self.max_candidate-prefix_size,available_tail)
                    if prefix_size+tail_size>self.max_candidate: reason="candidate_size_limit"; raise StopIteration
                    needed=prefix_size+tail_size
                    if reads+needed>self.max_reads: reason="read_limit"; raise StopIteration
                    prefix=self.source.read_at(self.sig,prefix_size)
                    tail=self.source.read_at(continuation,tail_size); reads+=needed
                    source_ranges.extend(((self.sig,self.sig+len(prefix)),
                        (continuation,continuation+len(tail))))
                    peak=max(peak,len(prefix)+len(tail)+3*len(prefix+tail)
                        +sum(len(h[2]) for h in found)+4*1024*1024)
                    if peak>self.max_memory: reason="memory_limit"; raise StopIteration
                    eoi_search=0; candidate=None
                    while True:
                        eoi=tail.find(b"\xff\xd9",eoi_search)
                        if eoi<0: break
                        eoi_checks+=1
                        possible=prefix+tail[:eoi+2]
                        peak=max(peak,3*len(possible)+sum(len(h[2]) for h in found)
                            +4*1024*1024)
                        if peak>self.max_memory: reason="memory_limit"; raise StopIteration
                        if valid_jpeg(possible):
                            decoder_calls+=1
                            try: _decoded,decode_warnings=decode_jpeg_with_warnings(possible)
                            except Exception: decoder_errors+=1
                            else:
                                if decode_warnings: decoder_warnings+=1
                                candidate=possible; break
                        eoi_search=eoi+2
                    if candidate is None:
                        if tail_size<available_tail: reason="candidate_size_limit"; raise StopIteration
                        if self.clock()-started>=self.max_seconds: reason="time_limit"; raise StopIteration
                        continue
                    found.append((cut,continuation,candidate))
                    if self.clock()-started>=self.max_seconds: reason="time_limit"; raise StopIteration
                    if len(found)>1: reason="ambiguous"; raise StopIteration
            if found and pairs < len(cuts)*len(starts): reason="combination_limit"
        except StopIteration: pass
        except Exception as exc: reason=f"error:{type(exc).__name__}:{exc}"
        merged=[]
        for start,end in sorted(source_ranges):
            if end<=start: continue
            if merged and start<=merged[-1][1]: merged[-1][1]=max(merged[-1][1],end)
            else: merged.append([start,end])
        unique=sum(end-start for start,end in merged)
        return JpegResult(tuple(found),cut_points_considered,pairs,reads,self.clock()-started,
            peak,reason,0,decoder_calls,decoder_warnings,unique,eoi_checks,decoder_errors)


class JpegEvidenceDiscovery(JpegFragmentDiscovery):
    """Cached Phase 3B.1 path with strict marker/RST checks before decoding.

    It preserves the same geometry-derived cuts, candidate starts and pair
    order. The marker scanner can safely reject malformed framing/restart
    sequences; Pillow remains secondary structural evidence, never integrity.
    """
    def run(self):
        started=self.clock(); pairs=peak=reads=points=rejected=decodes=warned=decoder_errors=0
        found=[]; reason="search_exhausted"; source_ranges=[]; external_cache={}
        try:
            if self.alignment < 1: raise ValueError("alignment must be positive")
            cut_end=min(self.source.size,self.sig+self.max_candidate)
            initial_size=cut_end-self.sig
            if initial_size>self.max_reads:
                reason="read_limit"; raise StopIteration
            initial=self.source.read_at(self.sig,initial_size); reads+=len(initial)
            source_ranges.append((self.sig,self.sig+len(initial)))
            if len(initial)>self.max_memory:
                reason="memory_limit"; raise StopIteration
            cuts=list(range(self.sig+self.alignment,cut_end,self.alignment))
            points=len(cuts); starts=[]
            for lo,hi in self.ranges:
                if lo<0 or hi<=lo or hi>self.source.size: raise ValueError("invalid candidate range")
                pos=((lo+self.alignment-1)//self.alignment)*self.alignment
                while pos<hi: starts.append(pos); pos+=self.alignment

            def get_segment(offset,size):
                nonlocal reads,reason
                if self.sig<=offset and offset+size<=cut_end:
                    return memoryview(initial)[offset-self.sig:offset-self.sig+size]
                key=(offset,size)
                if key in external_cache: return external_cache[key]
                if reads+size>self.max_reads:
                    reason="read_limit"; raise StopIteration
                if self.clock()-started>=self.max_seconds:
                    reason="time_limit"; raise StopIteration
                value=self.source.read_at(offset,size); reads+=len(value)
                source_ranges.append((offset,offset+len(value)))
                external_cache[key]=value
                return value

            for cut in cuts:
                for continuation in starts:
                    if pairs>=self.max_pairs:
                        reason="combination_limit"; raise StopIteration
                    if self.clock()-started>=self.max_seconds:
                        reason="time_limit"; raise StopIteration
                    pairs+=1
                    prefix_size=cut-self.sig
                    if prefix_size>=self.max_candidate:
                        reason="candidate_size_limit"; raise StopIteration
                    available_tail=self.source.size-continuation
                    tail_size=min(self.max_candidate-prefix_size,available_tail)
                    prefix=get_segment(self.sig,prefix_size)
                    tail=get_segment(continuation,tail_size)
                    tail_bytes=bytes(tail)
                    candidate=bytes(prefix)+tail_bytes
                    cache_bytes=sum(len(item) for item in external_cache.values())
                    # Includes the input window, cached external reads, up to
                    # three candidate copies and a conservative 4 MiB decoded
                    # pixel allowance; it is not process RSS/native heap.
                    peak=max(peak,len(initial)+cache_bytes+3*len(candidate)
                        +sum(len(item[2]) for item in found)+4*1024*1024)
                    if peak>self.max_memory:
                        reason="memory_limit"; raise StopIteration
                    candidate_found=None
                    search_from=0
                    while True:
                        eoi=tail_bytes.find(b"\xff\xd9",search_from)
                        if eoi<0: break
                        possible=candidate[:prefix_size]+tail_bytes[:eoi+2]
                        valid,frame,scan_count,rst_count=strict_jpeg_scan(possible)
                        if valid and valid_jpeg(possible):
                            decodes+=1
                            try:
                                _decoded,decode_warnings=decode_jpeg_with_warnings(possible)
                            except Exception:
                                decoder_errors+=1
                            else:
                                if decode_warnings: warned+=1
                                candidate_found=possible
                                break
                        else:
                            rejected+=1
                        search_from=eoi+2
                    if candidate_found is None:
                        if tail_size<available_tail:
                            reason="candidate_size_limit"; raise StopIteration
                        continue
                    found.append((cut,continuation,candidate_found))
                    if len(found)>1:
                        reason="ambiguous"; raise StopIteration
                    if self.clock()-started>=self.max_seconds:
                        reason="time_limit"; raise StopIteration
            if found and pairs < len(cuts)*len(starts):
                reason="combination_limit"
        except StopIteration:
            pass
        except Exception as exc:
            reason=f"error:{type(exc).__name__}:{exc}"
        merged=[]
        for start,end in sorted(source_ranges):
            if end<=start: continue
            if merged and start<=merged[-1][1]:
                merged[-1][1]=max(merged[-1][1],end)
            else: merged.append([start,end])
        unique=sum(end-start for start,end in merged)
        return JpegResult(tuple(found),points,pairs,reads,self.clock()-started,peak,reason,
            rejected,decodes,warned,unique,decodes+rejected,decoder_errors)


class JpegExperimentTests(unittest.TestCase):
    def test_baseline_progressive_quality_and_restart_fixtures_decode(self):
        cases=((False,55,None),(False,92,4),(True,68,None),(True,90,4))
        for progressive,quality,restart in cases:
            with self.subTest(progressive=progressive,quality=quality,restart=restart):
                data=jpeg_fixture(progressive=progressive,quality=quality,restart_blocks=restart)
                self.assertEqual(decode_jpeg(data),("JPEG",(128,128),"RGB"))
                summary=marker_summary(data)
                self.assertEqual(summary["frame"],"progressive" if progressive else "baseline")
                self.assertGreaterEqual(summary["scans"],2 if progressive else 1)
                self.assertEqual(summary["restart_interval"],4 if restart else None)
                if restart: self.assertGreater(summary["restart_markers"],0)
                self.assertTrue(summary["eoi"])
                strict,frame,scans,restarts_seen=strict_jpeg_scan(data)
                self.assertTrue(strict)
                self.assertEqual(frame,summary["frame"])
                self.assertEqual(scans,summary["scans"])
                self.assertEqual(restarts_seen,summary["restart_markers"])
                self.assertEqual(decode_jpeg_with_warnings(data)[1],())

    def test_restart_sequence_validation_is_a_safe_rejector(self):
        data=jpeg_fixture(progressive=False,quality=88,restart_blocks=4)
        marker=data.find(b"\xff\xd0")
        self.assertGreaterEqual(marker,0)
        corrupted=bytearray(data); corrupted[marker+1]=0xd3
        valid,reason,_scans,_restarts=strict_jpeg_scan(bytes(corrupted))
        self.assertFalse(valid)
        self.assertEqual(reason,"restart_sequence")

    def test_cached_marker_path_preserves_candidate_coverage_and_reports_work(self):
        original=jpeg_fixture(progressive=True,quality=76,seed=95,restart_blocks=4)
        cut=ALIGNMENT
        source_data=bytearray(original[:cut]); source_data.extend(b"\xa5"*(ALIGNMENT*2-cut))
        true_offset=len(source_data); source_data.extend(original[cut:])
        class Reader:
            def __init__(self,data): self.data=bytes(data); self.size=len(data); self.reads=0
            def read_at(self,o,n): self.reads+=n; return self.data[o:o+n]
        baseline_reader=Reader(source_data); baseline=JpegFragmentDiscovery(
            baseline_reader,signature_offset=0,
            candidate_ranges=((true_offset-1,true_offset+1),)).run()
        optimized_reader=Reader(source_data); optimized=JpegEvidenceDiscovery(
            optimized_reader,signature_offset=0,
            candidate_ranges=((true_offset-1,true_offset+1),)).run()
        expected=hashlib.sha256(original).digest()
        baseline_matches=[h for h in baseline.hypotheses if hashlib.sha256(h[2]).digest()==expected]
        optimized_matches=[h for h in optimized.hypotheses if hashlib.sha256(h[2]).digest()==expected]
        self.assertEqual(len(baseline_matches),1)
        self.assertEqual(len(optimized_matches),1)
        self.assertLessEqual(optimized.unique_bytes_read,baseline.bytes_read)
        self.assertLessEqual(optimized.bytes_read,baseline.bytes_read)
        self.assertLessEqual(optimized.pairs,PAIR_LIMIT)
        self.assertLessEqual(optimized.peak_buffer_estimate,MEMORY_LIMIT)
        self.assertGreater(optimized.decoder_calls,0)
        self.assertEqual(optimized.decoder_errors,0)
        self.assertEqual(optimized.decoder_warning_candidates,0)
        self.assertIn(optimized.classification,("structural_hypothesis","ambiguous"))
        if optimized.stop_reason=="ambiguous":
            self.assertGreater(len(optimized.hypotheses),1)

    def test_jpeg_holdout_variants_match_baseline_candidate_evidence(self):
        cases=((96,64,False,63,311,None),(160,96,True,89,312,4))
        for width,height,progressive,quality,seed,restart in cases:
            with self.subTest(size=(width,height),progressive=progressive,restart=restart):
                original=jpeg_fixture(width=width,height=height,progressive=progressive,
                    quality=quality,seed=seed,restart_blocks=restart)
                cut=ALIGNMENT
                source=bytearray(original[:cut]); source.extend(b"\xa5"*(ALIGNMENT*2-cut))
                true_offset=len(source); source.extend(original[cut:])
                class Reader:
                    def __init__(self,d): self.data=bytes(d); self.size=len(d); self.reads=0
                    def read_at(self,o,n): self.reads+=n; return self.data[o:o+n]
                ranges=((true_offset-1,true_offset+1),)
                baseline=JpegFragmentDiscovery(Reader(source),signature_offset=0,
                    candidate_ranges=ranges).run()
                optimized=JpegEvidenceDiscovery(Reader(source),signature_offset=0,
                    candidate_ranges=ranges).run()
                baseline_hashes={hashlib.sha256(item[2]).digest() for item in baseline.hypotheses}
                optimized_hashes={hashlib.sha256(item[2]).digest() for item in optimized.hypotheses}
                self.assertEqual(optimized_hashes,baseline_hashes)
                self.assertLessEqual(optimized.bytes_read,baseline.bytes_read)
                self.assertLessEqual(optimized.pairs,PAIR_LIMIT)
                self.assertLessEqual(optimized.peak_buffer_estimate,MEMORY_LIMIT)
                self.assertIn(hashlib.sha256(original).digest(),optimized_hashes)
                if optimized.stop_reason in ("combination_limit","read_limit","time_limit",
                    "memory_limit","candidate_size_limit"):
                    self.assertEqual(optimized.classification,"limit_reached")

    def test_cluster_aligned_two_fragment_decode_is_hypothesis_not_integrity(self):
        original=jpeg_fixture(progressive=False,quality=82)
        self.assertGreater(len(original),ALIGNMENT*2)
        cut=ALIGNMENT  # fixture oracle only; algorithm receives alignment, not cut
        continuation=ALIGNMENT*2
        source=bytearray(original[:cut])
        while len(source)<continuation: source.append(0xa5)
        true_offset=len(source); source.extend(original[cut:])
        class Reader:
            def __init__(self,data): self.data=bytes(data); self.size=len(data); self.reads=0
            def read_at(self,offset,size): self.reads+=size; return self.data[offset:offset+size]
        reader=Reader(source)
        experiment=JpegFragmentDiscovery(reader,signature_offset=0,candidate_ranges=((true_offset-ALIGNMENT,len(source)),))
        result=experiment.run()
        matches=[h for h in result.hypotheses if hashlib.sha256(h[2]).digest()==hashlib.sha256(original).digest()]
        self.assertTrue(result.hypotheses or result.stop_reason!="search_exhausted")
        self.assertLessEqual(result.pairs,PAIR_LIMIT)
        # Whether structural and decoder evidence finds the oracle is recorded
        # after search; successful decode alone is never called integrity.
        self.assertEqual(len(matches),1)
        self.assertEqual(decode_jpeg(original)[0],"JPEG")
        contiguous_result=_carve_contiguous_jpeg(bytes(source))
        # The contiguous validator may accept a false candidate containing
        # foreign entropy bytes; it must not be mistaken for the oracle file.
        self.assertIsNotNone(contiguous_result)
        self.assertNotEqual(hashlib.sha256(contiguous_result).digest(),hashlib.sha256(original).digest())
        self.assertEqual(_carve_contiguous_jpeg(original),original)

    def test_two_decodable_candidate_locations_remain_ambiguous(self):
        original=jpeg_fixture(progressive=True,quality=78)
        cut=ALIGNMENT; gap=ALIGNMENT*2-len(original[:cut])
        data=bytearray(original[:cut]); data.extend(b"G"*gap); a=len(data); data.extend(original[cut:])
        data.extend(b"H"*(ALIGNMENT-(len(data)%ALIGNMENT))); b=len(data); data.extend(original[cut:])
        class Reader:
            def __init__(self,d): self.data=bytes(d); self.size=len(d); self.reads=0
            def read_at(self,o,n): self.reads+=n; return self.data[o:o+n]
        reader=Reader(data)
        result=JpegFragmentDiscovery(reader,signature_offset=0,
            candidate_ranges=((a-1,a+1),(b-1,b+1))).run()
        # Preserve ambiguity when multiple candidate locations decode, even
        # when they produce identical bytes. No oracle selects one location.
        self.assertEqual(result.stop_reason,"ambiguous")
        self.assertEqual(len(result.hypotheses),2)
        self.assertLessEqual(result.pairs,PAIR_LIMIT)
        matching=[h for h in result.hypotheses if hashlib.sha256(h[2]).digest()==hashlib.sha256(original).digest()]
        self.assertTrue(matching)

    def test_similar_image_false_tail_stays_ambiguous_with_and_without_restarts(self):
        for restart in (None,4):
            with self.subTest(restart=restart):
                original,decoy=similar_jpeg_fixtures(restart_blocks=restart)
                cut=ALIGNMENT
                self.assertEqual(original[:cut],decoy[:cut])
                self.assertNotEqual(hashlib.sha256(original).digest(),hashlib.sha256(decoy).digest())
                data=bytearray(original[:cut]); data.extend(b"F"*(ALIGNMENT*2-cut))
                first=len(data); data.extend(original[cut:])
                data.extend(b"G"*((ALIGNMENT-len(data)%ALIGNMENT)%ALIGNMENT))
                second=len(data); data.extend(decoy[cut:])
                class Reader:
                    def __init__(self,d): self.data=bytes(d); self.size=len(d); self.reads=0
                    def read_at(self,o,n): self.reads+=n; return self.data[o:o+n]
                result=JpegEvidenceDiscovery(Reader(data),signature_offset=0,
                    candidate_ranges=((first-1,first+1),(second-1,second+1))).run()
                self.assertIn(result.stop_reason,("ambiguous","combination_limit","time_limit"))
                self.assertLessEqual(result.pairs,PAIR_LIMIT)
                hashes={hashlib.sha256(item[2]).digest() for item in result.hypotheses}
                self.assertIn(hashlib.sha256(original).digest(),hashes)
                self.assertIn(hashlib.sha256(decoy).digest(),hashes)
                self.assertEqual(result.stop_reason,"ambiguous")
                # A same-prefix decoy survives both marker and decoder checks;
                # that must remain an ambiguity, never an oracle-selected win.
                broad=JpegEvidenceDiscovery(Reader(data),signature_offset=0,
                    candidate_ranges=((first-ALIGNMENT,len(data)),)).run()
                expected_hashes={hashlib.sha256(original).digest(),hashlib.sha256(decoy).digest()}
                broad_hashes={hashlib.sha256(item[2]).digest() for item in broad.hypotheses}
                self.assertEqual(broad.stop_reason,"ambiguous")
                self.assertTrue(any(digest not in expected_hashes for digest in broad_hashes))

    def test_contiguous_carver_baseline_and_fragmented_carver_control(self):
        image=jpeg_fixture(progressive=True,quality=84)
        self.assertTrue(valid_jpeg(image))
        self.assertEqual(_carve_contiguous_jpeg(image),image)

    def test_missing_and_partially_overwritten_fragments_are_rejected(self):
        original=jpeg_fixture(progressive=True,quality=80)
        cut=ALIGNMENT; continuation=ALIGNMENT*2
        overwritten=bytearray(original[cut:]); overwritten[len(overwritten)//2]^=0x7f
        for tail in (b"foreign bytes",bytes(overwritten)):
            with self.subTest(tail=tail[:6]):
                data=bytearray(original[:cut])
                data.extend(b"\xa5"*(continuation-len(data)))
                target=len(data); data.extend(tail)
                class Reader:
                    def __init__(self,d): self.data=bytes(d); self.size=len(d); self.reads=0
                    def read_at(self,o,n): self.reads+=n; return self.data[o:o+n]
                reader=Reader(data)
                result=JpegFragmentDiscovery(reader,signature_offset=0,
                    candidate_ranges=((target-ALIGNMENT,len(data)),)).run()
                matches=[h for h in result.hypotheses if hashlib.sha256(h[2]).digest()==hashlib.sha256(original).digest()]
                # A decoder may accept a plausible but wrong entropy stream;
                # only the test oracle can say this is not the original.
                self.assertFalse(matches)
                self.assertIn(result.stop_reason,("search_exhausted","combination_limit","ambiguous"))

    def test_jpeg_budgets_and_injected_monotonic_clock(self):
        image=jpeg_fixture(progressive=False,quality=80)
        cut=ALIGNMENT; continuation=ALIGNMENT*2
        data=bytearray(image[:cut]); data.extend(b"\xa5"*(continuation-len(data)))
        true_offset=len(data); data.extend(image[cut:])
        class Reader:
            def __init__(self,d): self.data=bytes(d); self.size=len(d); self.reads=0
            def read_at(self,o,n): self.reads+=n; return self.data[o:o+n]
        class Clock:
            def __init__(self): self.now=0.0
            def __call__(self): self.now+=0.01; return self.now
        cases=((dict(max_pairs=1),None,"combination_limit"),
               (dict(max_reads=1),None,"read_limit"),
               (dict(max_memory=1),None,"memory_limit"),
               (dict(max_candidate=5000),None,"candidate_size_limit"),
               (dict(max_seconds=0.001),Clock(),"time_limit"))
        for limits,clock,expected in cases:
            for cls in (JpegFragmentDiscovery,JpegEvidenceDiscovery):
                result=cls(Reader(data),signature_offset=0,
                    candidate_ranges=((true_offset-ALIGNMENT,len(data)),),monotonic=clock or time.monotonic,**limits).run()
                self.assertEqual(result.stop_reason,expected)
                self.assertEqual(result.classification,"limit_reached")
                self.assertLessEqual(result.pairs,PAIR_LIMIT)
        # A truly contiguous image is accepted by the current validator. This
        # experiment does not claim a production change to the carver.
        self.assertEqual(decode_jpeg(image)[0],"JPEG")

if __name__=="__main__": unittest.main()








