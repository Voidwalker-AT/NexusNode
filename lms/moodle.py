"""
NexusNode — Moodle LMS Provider Implementation
Authoritative provider implementation for UPES Moodle LMS (https://lms.upes.ac.in).
Uses Direct Authenticated HTTP with in-memory session cookies for high performance,
and integrates with BrowserService for interactive draft submission workflows.
"""

import re
import os
import time
import json
import hashlib
import logging
import urllib.request
import urllib.error
from html.parser import HTMLParser
from typing import List, Optional, Dict, Any, Tuple

import config
from .base import LMSProvider
from .models import (
    LMSCourse,
    LMSResource,
    LMSAssignment,
    ResourceType,
    SubmissionPlan,
    SubmissionState
)
from .errors import (
    LMSAuthRequiredError,
    LMSPageChangedError,
    LMSAmbiguousCourseError,
    LMSResourceNotFoundError,
    LMSAssignmentNotFoundError,
    SubmissionConsequentialBlockedError
)

logger = logging.getLogger("NEXUS_MOODLE_PROVIDER")


class MoodleHTMLParser(HTMLParser):
    """Safe, zero-dependency HTML parser for Moodle dashboard and course outlines."""

    def __init__(self):
        super().__init__()
        self.courses: List[Dict[str, Any]] = []
        self.resources: List[Dict[str, Any]] = []
        self.assignments: List[Dict[str, Any]] = []
        self.current_section: Optional[str] = None

    def feed(self, data: str):
        # Extract section titles if present
        section_matches = re.findall(r'<h[234][^>]*class="[^"]*sectionname[^"]*"[^>]*>(.*?)</h[234]>', data, re.DOTALL | re.IGNORECASE)
        if section_matches:
            self.current_section = re.sub(r'<[^>]+>', '', section_matches[0]).strip()

        # Regex pass for robust extraction across nested tags
        links = re.findall(r'<a\s+[^>]*href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>', data, re.DOTALL | re.IGNORECASE)
        for href, raw_text in links:
            clean_text = re.sub(r'<[^>]+>', ' ', raw_text).strip()
            clean_text = " ".join(clean_text.split())
            
            # Course detection
            if "/course/view.php" in href:
                m = re.search(r"id=(\d+)", href)
                if m and clean_text and len(clean_text) > 3:
                    cid = m.group(1)
                    cname = re.sub(r"^Course\s+name\s*", "", clean_text, flags=re.IGNORECASE).strip()
                    if cname and not any(c["id"] == cid for c in self.courses):
                        self.courses.append({"id": cid, "name": cname, "url": href})

            # Resource detection
            if "/mod/resource/view.php" in href or "/mod/folder/view.php" in href or "/mod/page/view.php" in href or ".pdf" in href.lower():
                m = re.search(r"id=(\d+)", href)
                res_id = m.group(1) if m else str(abs(hash(href)) % 1000000)
                res_type = ResourceType.PDF if (".pdf" in href.lower() or "pdf" in clean_text.lower()) else (
                    ResourceType.FOLDER if "/mod/folder/" in href else ResourceType.FILE
                )
                clean_title = re.sub(r"\s+(File|Page)$", "", clean_text, flags=re.IGNORECASE).strip() or "Course Resource"
                if not any(r["id"] == res_id for r in self.resources):
                    self.resources.append({
                        "id": res_id,
                        "title": clean_title,
                        "url": href,
                        "type": res_type,
                        "section": self.current_section
                    })

            # Assignment detection
            if "/mod/assign/view.php" in href:
                m = re.search(r"id=(\d+)", href)
                assign_id = m.group(1) if m else str(abs(hash(href)) % 1000000)
                clean_title = re.sub(r"\s+Assignment$", "", clean_text, flags=re.IGNORECASE).strip() or "Assignment"
                if not any(a["id"] == assign_id for a in self.assignments):
                    self.assignments.append({
                        "id": assign_id,
                        "title": clean_title,
                        "url": href
                    })


class MoodleProvider(LMSProvider):
    """Moodle LMS provider implementation for UPES LMS."""

    def __init__(self, base_url: str = "https://lms.upes.ac.in", browser_service=None):
        self.base_url = base_url.rstrip("/")
        self.browser_service = browser_service
        self._cached_cookies: Optional[str] = None
        self._cookie_fetched_at: float = 0.0

    @property
    def provider_name(self) -> str:
        return "moodle"

    def _get_active_session_cookie(self) -> str:
        """
        Retrieves active MoodleSession cookie from the dedicated browser profile.
        Keeps cookies in-memory without persistent plaintext leakage.
        """
        now = time.time()
        if self._cached_cookies and (now - self._cookie_fetched_at) < 300:
            return self._cached_cookies

        # Query active CDP / PinchTab browser session
        try:
            req = urllib.request.urlopen("http://127.0.0.1:9868/json", timeout=2)
            tabs = json.loads(req.read().decode())
            page_tabs = [t for t in tabs if t.get("type") == "page"]
            if page_tabs:
                ws_url = page_tabs[0].get("webSocketDebuggerUrl")
                if ws_url:
                    import asyncio
                    import websockets
                    async def fetch_c():
                        async with websockets.connect(ws_url) as ws:
                            await ws.send(json.dumps({"id": 1, "method": "Network.getCookies", "params": {"urls": [self.base_url]}}))
                            res = json.loads(await ws.recv())
                            cookies = res.get("result", {}).get("cookies", [])
                            return "; ".join([f"{c['name']}={c['value']}" for c in cookies if c.get("name") in ("MoodleSession", "SimpleSAMLAuthToken", "SimpleSAMLSessionID")])
                    cookie_header = asyncio.run(fetch_c())
                    if cookie_header:
                        self._cached_cookies = cookie_header
                        self._cookie_fetched_at = now
                        return cookie_header
        except Exception as e:
            logger.debug(f"Direct CDP cookie query fallback: {e}")

        if self._cached_cookies:
            return self._cached_cookies
        return ""

    def _http_get(self, url: str) -> Tuple[str, str]:
        """
        Performs authenticated HTTP GET against Moodle.
        Returns tuple of (response_text, final_url).
        Raises LMSAuthRequiredError if unauthenticated or redirected to login.
        """
        cookie_header = self._get_active_session_cookie()
        if not cookie_header or "MoodleSession" not in cookie_header:
            raise LMSAuthRequiredError("Moodle session cookie not found. Authentication required.")

        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
            "Cookie": cookie_header,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })
        
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                final_url = resp.geturl()
                if (not final_url.startswith(self.base_url) 
                    or "/login" in final_url 
                    or "auth/login" in final_url 
                    or "connectportal" in final_url):
                    self._cached_cookies = None
                    raise LMSAuthRequiredError("Moodle session expired; redirected to login/portal.")
                body = resp.read().decode("utf-8", errors="replace")
                return body, final_url
        except urllib.error.HTTPError as he:
            if he.code in (401, 403):
                self._cached_cookies = None
                raise LMSAuthRequiredError(f"Moodle returned HTTP {he.code}: Unauthorized.")
            raise LMSPageChangedError(f"Moodle returned HTTP {he.code} on {url}.")
        except urllib.error.URLError as ue:
            raise LMSAuthRequiredError(f"Cannot connect to LMS host: {ue.reason}")

    def check_auth(self) -> bool:
        """Verifies whether the current Moodle session is authenticated."""
        try:
            _, final_url = self._http_get(f"{self.base_url}/my/courses.php")
            return "/login" not in final_url
        except Exception:
            return False

    def list_courses(self, query: Optional[str] = None, active_only: bool = True) -> Tuple[List[LMSCourse], str]:
        """Lists enrolled courses from /my/courses.php via Direct HTTP AJAX or HTML parsing."""
        html_content, _ = self._http_get(f"{self.base_url}/my/courses.php")
        courses: List[LMSCourse] = []

        # 1. Try Moodle core_course_get_enrolled_courses_by_timeline_classification via direct HTTP AJAX
        sesskey_match = re.search(r'"sesskey":"([^"]+)"', html_content) or re.search(r'sesskey=([^"&]+)', html_content)
        if sesskey_match:
            sesskey = sesskey_match.group(1)
            ajax_url = f"{self.base_url}/lib/ajax/service.php?sesskey={sesskey}&info=core_course_get_enrolled_courses_by_timeline_classification"
            payload = [{
                "index": 0,
                "methodname": "core_course_get_enrolled_courses_by_timeline_classification",
                "args": {
                    "offset": 0,
                    "limit": 100,
                    "classification": "all",
                    "sort": "fullname"
                }
            }]
            cookie_header = self._get_active_session_cookie()
            req = urllib.request.Request(ajax_url, data=json.dumps(payload).encode('utf-8'), headers={
                "Content-Type": "application/json",
                "Cookie": cookie_header,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
            })
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res_data = json.loads(resp.read().decode('utf-8'))
                    raw_courses = res_data[0].get("data", {}).get("courses", [])
                    for rc in raw_courses:
                        cid = str(rc.get("id"))
                        cname = rc.get("fullname", f"Course {cid}").strip()
                        cshort = rc.get("shortname", "").strip() or cname[:20]
                        cur_url = rc.get("viewurl") or f"{self.base_url}/course/view.php?id={cid}"
                        
                        sem_match = re.search(r"(Sem\d+)", cname, re.IGNORECASE)
                        semester = sem_match.group(1) if sem_match else "Sem5"

                        is_active = "Sem5" in cname or "Sem5" in cshort or rc.get("progress", 0) is not None

                        courses.append(LMSCourse(
                            course_id=f"lmscourse_{cid}",
                            name=cname,
                            short_name=cshort,
                            provider_id=cid,
                            url=cur_url,
                            semester=semester,
                            provider="moodle",
                            is_active=is_active
                        ))
            except Exception as e:
                logger.warning(f"Moodle AJAX course query fallback: {e}")

        # 2. Fallback to HTML parser if AJAX returned empty
        if not courses:
            parser = MoodleHTMLParser()
            parser.feed(html_content)
            for c in parser.courses:
                name = c["name"]
                provider_id = c["id"]
                normalized_id = f"lmscourse_{provider_id}"
                short_match = re.search(r"([A-Z0-9\s]+)_Sem\d+", name)
                short_name = short_match.group(0).strip() if short_match else name[:20]
                semester_match = re.search(r"(Sem\d+)", name, re.IGNORECASE)
                semester = semester_match.group(1) if semester_match else "Sem5"

                courses.append(LMSCourse(
                    course_id=normalized_id,
                    name=name,
                    short_name=short_name,
                    provider_id=provider_id,
                    url=c["url"],
                    semester=semester,
                    provider="moodle",
                    is_active=True
                ))

        # Filter by active_only if requested
        if active_only:
            active_courses = [c for c in courses if c.is_active or "Sem5" in c.name or "Sem5" in c.short_name]
            if active_courses:
                courses = active_courses

        # Filter by query if supplied
        if query:
            q_norm = query.strip().lower()
            filtered = []
            for c in courses:
                # Derive acronym from course title words (e.g. "Cryptography and Network Security" -> "cns")
                words = [w for w in re.findall(r'[A-Za-z]+', c.name) if w.lower() not in ('and', 'of', 'in', 'the', 'for', 'sem', 'sem5')]
                acronym = "".join(w[0] for w in words).lower()

                if (q_norm in c.name.lower() or
                    q_norm in c.short_name.lower() or
                    q_norm in c.course_id.lower() or
                    q_norm == c.provider_id or
                    q_norm == acronym or
                    q_norm in acronym):
                    filtered.append(c)
            return filtered, "direct_http"

        return courses, "direct_http"

    def get_course(self, course_id: str) -> Tuple[Optional[LMSCourse], Dict[str, Any], str]:
        """Gets course outline, sections, and resources."""
        clean_id = course_id.replace("lmscourse_", "").strip()
        course_url = f"{self.base_url}/course/view.php?id={clean_id}"
        html_content, _ = self._http_get(course_url)
        
        parser = MoodleHTMLParser()
        parser.feed(html_content)
        
        # Extract title from title tag or h1
        title_match = re.search(r"<title>(.*?)</title>", html_content, re.IGNORECASE)
        page_title = title_match.group(1).replace("Course:", "").replace("| UPES LMS", "").strip() if title_match else f"Course {clean_id}"

        course = LMSCourse(
            course_id=f"lmscourse_{clean_id}",
            name=page_title,
            short_name=page_title[:20],
            provider_id=clean_id,
            url=course_url,
            semester="Sem5",
            provider="moodle",
            is_active=True
        )

        sections = []
        # Find topics/modules in page
        section_titles = re.findall(r'<h3 class="sectionname[^>]*>(.*?)</h3>', html_content, re.IGNORECASE)
        for st in section_titles:
            clean_st = re.sub(r"<[^>]+>", "", st).strip()
            if clean_st:
                sections.append(clean_st)

        outline = {
            "course": course.to_dict(),
            "sections": sections,
            "resource_count": len(parser.resources),
            "assignment_count": len(parser.assignments),
            "resources": parser.resources,
            "assignments": parser.assignments
        }
        return course, outline, "direct_http"

    def list_resources(self, course_id: str, section: Optional[str] = None) -> Tuple[List[LMSResource], str]:
        """Lists resources in a course outline."""
        clean_id = course_id.replace("lmscourse_", "").strip()
        course_url = f"{self.base_url}/course/view.php?id={clean_id}"
        html_content, _ = self._http_get(course_url)
        
        parser = MoodleHTMLParser()
        parser.feed(html_content)

        resources: List[LMSResource] = []
        for r in parser.resources:
            res_id = f"lmsres_{r['id']}"
            res = LMSResource(
                resource_id=res_id,
                course_id=f"lmscourse_{clean_id}",
                title=r["title"],
                resource_type=r["type"],
                section=r.get("section"),
                downloadable=True,
                external=False,
                url=r["url"],
                provider_id=r["id"]
            )
            resources.append(res)
        return resources, "direct_http"

    def download_resource(self, resource_id: str, dest_vault_abs_path: str, max_bytes: int = 52428800) -> Dict[str, Any]:
        """
        Downloads a resource file directly into the designated destination in the Vault.
        Enforces maximum download byte limits (default 50 MB / 52,428,800 bytes).
        """
        clean_id = resource_id.replace("lmsres_", "").strip()
        cookie_header = self._get_active_session_cookie()
        
        # Try candidate endpoints in order: /mod/resource/, /mod/page/, /mod/folder/
        candidate_urls = [
            f"{self.base_url}/mod/resource/view.php?id={clean_id}",
            f"{self.base_url}/mod/page/view.php?id={clean_id}",
            f"{self.base_url}/mod/folder/view.php?id={clean_id}"
        ]

        resp = None
        last_error = None
        download_url = candidate_urls[0]

        for curl in candidate_urls:
            download_url = curl
            req = urllib.request.Request(curl, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
                "Cookie": cookie_header
            })
            try:
                resp = urllib.request.urlopen(req, timeout=30)
                final_url = resp.geturl()
                if "/login" in final_url or "auth/login" in final_url:
                    raise LMSAuthRequiredError("Moodle session expired during resource download.")
                break
            except urllib.error.HTTPError as he:
                if he.code in (401, 403):
                    raise LMSAuthRequiredError("Moodle authentication required for resource download.")
                last_error = he
                continue
            except Exception as e:
                last_error = e
                continue

        if not resp:
            raise LMSResourceNotFoundError(f"Moodle resource download failed: {last_error}")

        try:
                
                content_len = resp.headers.get("Content-Length")
                if content_len and int(content_len) > max_bytes:
                    raise ValueError(f"Resource size ({content_len} bytes) exceeds maximum download limit ({max_bytes} bytes).")

                mime_type = str(resp.headers.get("Content-Type") or "application/octet-stream")
                content_disp = str(resp.headers.get("Content-Disposition") or "")
                
                # Extract filename from header or URL
                filename_match = re.search(r'filename="?([^";]+)"?', content_disp)
                filename = filename_match.group(1) if filename_match else f"resource_{clean_id}.bin"
                
                # If destination is a directory, append filename
                if os.path.isdir(dest_vault_abs_path) or not os.path.splitext(dest_vault_abs_path)[1]:
                    os.makedirs(dest_vault_abs_path, exist_ok=True)
                    final_path = os.path.join(dest_vault_abs_path, filename)
                else:
                    os.makedirs(os.path.dirname(dest_vault_abs_path), exist_ok=True)
                    final_path = dest_vault_abs_path

                # Read with streaming size check
                total_bytes = 0
                hasher = hashlib.sha256()
                with open(final_path, "wb") as out_f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            out_f.close()
                            if os.path.exists(final_path):
                                os.remove(final_path)
                            raise ValueError(f"Resource exceeded maximum download limit ({max_bytes} bytes).")
                        hasher.update(chunk)
                        out_f.write(chunk)

                return {
                    "vault_dest_path": final_path,
                    "filename": filename,
                    "mime_type": mime_type,
                    "size_bytes": total_bytes,
                    "sha256": hasher.hexdigest(),
                    "source_url": download_url,
                    "downloaded_at": time.time()
                }
        except urllib.error.HTTPError as he:
            if he.code in (401, 403):
                raise LMSAuthRequiredError("Moodle authentication required for resource download.")
            raise LMSResourceNotFoundError(f"Moodle resource download failed: HTTP {he.code}")

    def list_assignments(self, course_id: Optional[str] = None, upcoming_only: bool = False) -> Tuple[List[LMSAssignment], str]:
        """Lists assignments in a given course or across all active courses."""
        assignments: List[LMSAssignment] = []
        courses_to_scan = []

        if course_id:
            courses_to_scan = [course_id]
        else:
            all_courses, _ = self.list_courses(active_only=True)
            courses_to_scan = [c.course_id for c in all_courses[:6]]

        def _scan_course(cid: str) -> List[LMSAssignment]:
            clean_cid = cid.replace("lmscourse_", "").strip()
            course_url = f"{self.base_url}/course/view.php?id={clean_cid}"
            c_assigns = []
            try:
                html_content, _ = self._http_get(course_url)
                parser = MoodleHTMLParser()
                parser.feed(html_content)
                for a in parser.assignments:
                    assign = LMSAssignment(
                        assignment_id=f"lmsassign_{a['id']}",
                        course_id=f"lmscourse_{clean_cid}",
                        title=a["title"],
                        instructions="Assignment instructions available on assignment page.",
                        due_at=None,
                        status="OPEN",
                        submitted=False,
                        submission_allowed=True,
                        url=a["url"],
                        provider_id=a["id"]
                    )
                    c_assigns.append(assign)
            except Exception as e:
                logger.warning(f"Failed to scan assignments in course {cid}: {e}")
            return c_assigns

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(_scan_course, cid) for cid in courses_to_scan]
            for future in concurrent.futures.as_completed(futures):
                try:
                    res = future.result()
                    assignments.extend(res)
                except Exception as e:
                    logger.warning(f"Assignment scanning task error: {e}")

        return assignments, "direct_http"

    def get_assignment(self, assignment_id: str) -> Tuple[Optional[LMSAssignment], str]:
        """Retrieves detailed assignment information from /mod/assign/view.php."""
        clean_id = assignment_id.replace("lmsassign_", "").strip()
        assign_url = f"{self.base_url}/mod/assign/view.php?id={clean_id}"
        html_content, _ = self._http_get(assign_url)

        title_match = re.search(r"<h2[^>]*>(.*?)</h2>", html_content, re.IGNORECASE)
        title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else f"Assignment {clean_id}"

        # Extract instructions from intro block
        intro_match = re.search(r'<div class="submissionstatustable[^>]*>(.*?)</div>', html_content, re.IGNORECASE) or \
                      re.search(r'<div id="intro"[^>]*>(.*?)</div>', html_content, re.IGNORECASE)
        instructions = re.sub(r"<[^>]+>", " ", intro_match.group(1)).strip() if intro_match else "View assignment details in LMS."

        # Extract due date
        due_match = re.search(r"Due date.*?<td[^>]*>(.*?)</td>", html_content, re.IGNORECASE | re.DOTALL)
        due_at = re.sub(r"<[^>]+>", "", due_match.group(1)).strip() if due_match else None

        # Check submission status
        submitted = "Submitted for grading" in html_content
        status = "SUBMITTED" if submitted else ("OPEN" if "Add submission" in html_content or "Edit submission" in html_content else "CLOSED")
        
        # Check if final submit control exists
        final_control = "Submit assignment" in html_content or "Submit" in html_content

        assign = LMSAssignment(
            assignment_id=f"lmsassign_{clean_id}",
            course_id="",
            title=title,
            instructions=instructions,
            due_at=due_at,
            status=status,
            submitted=submitted,
            submission_allowed="Add submission" in html_content or "Edit submission" in html_content,
            url=assign_url,
            provider_id=clean_id,
            final_submission_control_present=final_control
        )
        return assign, "direct_http"

    def prepare_submission(
        self,
        assignment_id: str,
        vault_file_records: List[Dict[str, Any]],
        browser_service=None
    ) -> Tuple[Dict[str, Any], str]:
        """
        Interactive draft submission preparation.
        Bridges to BrowserService to navigate, verify page identity, attach files,
        and capture visual evidence.
        """
        clean_id = assignment_id.replace("lmsassign_", "").strip()
        assign_url = f"{self.base_url}/mod/assign/view.php?id={clean_id}"

        if not browser_service:
            raise LMSPageChangedError("BrowserService required for interactive submission preparation.")

        # Open dedicated session
        session_res = browser_service.open_session("admin", {"url": assign_url})
        if not session_res.ok:
            raise LMSAuthRequiredError(f"Failed to open browser session: {session_res.error}")
        
        session_id = session_res.data["session_id"]
        try:
            # Capture paired snapshot and screenshot
            cap_res = browser_service.capture("admin", {"session_id": session_id})
            if not cap_res.ok:
                raise LMSPageChangedError("Failed to capture assignment page state.")

            snapshot_text = cap_res.data.get("snapshot", {}).get("tree_text", "")
            screenshot_path = cap_res.data.get("screenshot", {}).get("artifact_path")
            capture_id = cap_res.data.get("capture_id")
            current_url = cap_res.data.get("url", "")

            # Multi-signal page identity verification
            page_verified = (
                clean_id in current_url or
                "/mod/assign/" in current_url
            )

            # Check if submission is allowed (e.g. "Add submission" or file input)
            has_add_submission = "Add submission" in snapshot_text or "Edit submission" in snapshot_text
            has_file_input = "file input" in snapshot_text.lower() or "[file]" in snapshot_text.lower()

            draft_verified = False
            # If "Add submission" button exists, click it safely
            if has_add_submission and not has_file_input:
                click_match = re.search(r'\[(e\d+)\]\s+(?:<button>|<link>|<a>)\s+Add submission', snapshot_text, re.IGNORECASE)
                if click_match:
                    elem_ref = click_match.group(1)
                    click_res = browser_service.click("admin", {"session_id": session_id, "element_ref": elem_ref})
                    if click_res.ok:
                        # Re-capture page after entering draft upload form
                        time.sleep(2)
                        cap2_res = browser_service.capture("admin", {"session_id": session_id})
                        if cap2_res.ok:
                            snapshot_text = cap2_res.data.get("snapshot", {}).get("tree_text", "")
                            screenshot_path = cap2_res.data.get("screenshot", {}).get("artifact_path")
                            capture_id = cap2_res.data.get("capture_id")
                            has_file_input = "file" in snapshot_text.lower()
                            draft_verified = True

            # If file input element exists, attach vault files
            attached_files = []
            if has_file_input:
                file_elem_match = re.search(r'\[(e\d+)\]\s+(?:<input type="file">|<file_input>|<input>)', snapshot_text, re.IGNORECASE)
                if file_elem_match:
                    elem_ref = file_elem_match.group(1)
                    for vf in vault_file_records:
                        up_res = browser_service.upload("admin", {"session_id": session_id, "element_ref": elem_ref, "vault_path": vf["vault_path"]})
                        if up_res.ok:
                            attached_files.append(vf["vault_path"])

            return {
                "page_verified": page_verified,
                "draft_upload_verified": draft_verified or len(attached_files) > 0,
                "attached_files": attached_files,
                "capture_id": capture_id,
                "screenshot_artifact": screenshot_path,
                "current_url": current_url,
                "final_action_required": True
            }, "browser"
        finally:
            # Clean up browser session
            browser_service.close_session("admin", {"session_id": session_id})

    def inspect_submission_status(
        self,
        assignment_id: str,
        browser_service=None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Inspects remote Moodle assignment page for positive evidence of submission.
        Used for verification and crash-recovery before triggering final submission.
        """
        clean_id = assignment_id.replace("lmsassign_", "").strip()
        assign_url = f"{self.base_url}/mod/assign/view.php?id={clean_id}"

        if not browser_service:
            return False, {"error": "BrowserService unavailable"}

        session_res = browser_service.open_session("admin", {"url": assign_url})
        if not session_res.ok:
            return False, {"error": session_res.error}

        session_id = session_res.data["session_id"]
        try:
            cap_res = browser_service.capture("admin", {"session_id": session_id})
            if not cap_res.ok:
                return False, {"error": "Failed to capture page"}

            tree_text = cap_res.data.get("snapshot", {}).get("tree_text", "")
            lower_tree = tree_text.lower()

            is_submitted = (
                "submitted for grading" in lower_tree or
                "submission status: submitted" in lower_tree or
                "status: submitted" in lower_tree
            )

            # Look for submission timestamp and files
            sub_time_match = re.search(r'last modified\s*:\s*([^\n\r]+)', tree_text, re.IGNORECASE)
            sub_time = sub_time_match.group(1).strip() if sub_time_match else None

            return is_submitted, {
                "assignment_id": assignment_id,
                "url": assign_url,
                "is_submitted": is_submitted,
                "submission_status": "submitted" if is_submitted else "draft_or_unsubmitted",
                "submitted_timestamp": sub_time,
                "capture_id": cap_res.data.get("capture_id"),
                "screenshot_artifact": cap_res.data.get("screenshot", {}).get("artifact_path")
            }
        finally:
            browser_service.close_session("admin", {"session_id": session_id})

    def submit_final_assignment(
        self,
        assignment_id: str,
        vault_file_records: List[Dict[str, Any]],
        browser_service=None,
        session_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any], str]:
        """
        Executes the final assignment submission sequence under privileged server-side control.
        Enforces positive proof verification and post-submit evidence capture.
        """
        clean_id = assignment_id.replace("lmsassign_", "").strip()
        assign_url = f"{self.base_url}/mod/assign/view.php?id={clean_id}"

        if not browser_service:
            return False, {"error": "BrowserService unavailable", "uncertain": True}, "error"

        # Check if remote assignment is already submitted before mutating
        already_submitted, status_info = self.inspect_submission_status(assignment_id, browser_service=browser_service)
        if already_submitted:
            logger.info(f"Assignment '{assignment_id}' is already submitted on Moodle.")
            return True, {
                "verified": True,
                "already_submitted": True,
                "submission_status": "submitted",
                "evidence": status_info
            }, "browser"

        # Open dedicated browser session for final submission execution
        close_when_done = session_id is None
        if not session_id:
            session_res = browser_service.open_session("admin", {"url": assign_url})
            if not session_res.ok:
                return False, {"error": f"Failed to open session: {session_res.error}", "uncertain": True}, "error"
            session_id = session_res.data["session_id"]

        try:
            # 1. Capture current assignment page
            cap_res = browser_service.capture("admin", {"session_id": session_id})
            if not cap_res.ok:
                return False, {"error": "Failed to capture initial submission page", "uncertain": True}, "browser"

            tree_text = cap_res.data.get("snapshot", {}).get("tree_text", "")
            current_url = cap_res.data.get("url", "")

            # Verify target URL corresponds to target assignment
            if clean_id not in current_url and "/mod/assign/" not in current_url:
                return False, {"error": f"Target page mismatch: '{current_url}' does not match assignment '{clean_id}'", "uncertain": True}, "browser"

            # 2. Locate Submit Assignment or Save Changes control
            # Note: Internal privileged executor operates through direct browser bridge interaction
            submit_match = re.search(r'\[(e\d+)\]\s+(?:<button>|<input[^>]*type="submit"[^>]*>|<a>)\s+Submit assignment', tree_text, re.IGNORECASE)
            save_match = re.search(r'\[(e\d+)\]\s+(?:<button>|<input[^>]*type="submit"[^>]*>)\s+Save changes', tree_text, re.IGNORECASE)

            target_elem = None
            if submit_match:
                target_elem = submit_match.group(1)
            elif save_match:
                target_elem = save_match.group(1)

            if not target_elem:
                # If neither is found, check if already submitted
                if "submitted for grading" in tree_text.lower():
                    return True, {
                        "verified": True,
                        "submission_status": "submitted",
                        "capture_id": cap_res.data.get("capture_id"),
                        "screenshot_artifact": cap_res.data.get("screenshot", {}).get("artifact_path")
                    }, "browser"
                return False, {"error": "No final submission control found on assignment page.", "uncertain": True}, "browser"

            # 3. Privileged internal click
            # Use low-level PinchTab bridge client directly to execute privileged final submit without MCP block
            if hasattr(browser_service, "pinchtab") and browser_service.pinchtab:
                client = browser_service.pinchtab
                client.click(session_id, target_elem)
            else:
                # Fallback for synthetic/mocked providers
                pass

            time.sleep(2)

            # 4. Check for Moodle Confirmation Page ("Confirm submission" / "Continue")
            cap2_res = browser_service.capture("admin", {"session_id": session_id})
            if cap2_res.ok:
                tree_text2 = cap2_res.data.get("snapshot", {}).get("tree_text", "")
                confirm_match = re.search(r'\[(e\d+)\]\s+(?:<button>|<input[^>]*type="submit"[^>]*>)\s+(?:Continue|Confirm)', tree_text2, re.IGNORECASE)
                if confirm_match and hasattr(browser_service, "pinchtab") and browser_service.pinchtab:
                    conf_elem = confirm_match.group(1)
                    browser_service.pinchtab.click(session_id, conf_elem)
                    time.sleep(2)

            # 5. Post-Submission Positive Proof Verification & Capture
            post_cap = browser_service.capture("admin", {"session_id": session_id})
            if not post_cap.ok:
                return False, {"error": "Failed to capture post-submission evidence.", "uncertain": True}, "browser"

            post_tree = post_cap.data.get("snapshot", {}).get("tree_text", "")
            post_screenshot = post_cap.data.get("screenshot", {}).get("artifact_path")
            post_capture_id = post_cap.data.get("capture_id")
            post_url = post_cap.data.get("url", "")

            # Positive verification
            is_verified = (
                "submitted for grading" in post_tree.lower() or
                "submission status: submitted" in post_tree.lower() or
                bool(re.search(r"submission status\s*:\s*submitted", post_tree, re.IGNORECASE))
            )

            if is_verified:
                return True, {
                    "verified": True,
                    "submission_status": "submitted",
                    "post_capture_id": post_capture_id,
                    "post_screenshot_artifact": post_screenshot,
                    "post_url": post_url,
                    "timestamp": time.time()
                }, "browser"
            else:
                # If positive proof is absent, classify as UNCERTAIN
                return False, {
                    "verified": False,
                    "uncertain": True,
                    "message": "Submission was dispatched, but post-submission confirmation status could not be verified.",
                    "post_capture_id": post_capture_id,
                    "post_screenshot_artifact": post_screenshot,
                    "post_url": post_url
                }, "browser"
        finally:
            if close_when_done:
                browser_service.close_session("admin", {"session_id": session_id})

