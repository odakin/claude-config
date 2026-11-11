// Google Classroom course engine: create / update, invite (parallel), announcements and coursework readback, roster match by address, coursework list, short answers without names; takes a googleapis classroom client, no imports.
//
// Every function takes the `classroom` client (googleapis `google.classroom({version: "v1", auth})`) as its
// first argument, so the caller owns the credentials and the googleapis install; this module needs neither.
// API behaviour behind each function (scopes, invitations only, PROVISIONED, attachments, address matching)
// = conventions/google-classroom-api.md. Hermetic test = scripts/lib/classroom-courses.test.mjs (fake client).

const UPDATABLE = ["name", "section", "descriptionHeading", "description", "room", "courseState"];

export function summarize(c) {
  return {
    id: c.id,
    name: c.name,
    section: c.section,
    room: c.room,
    state: c.courseState,
    enrollmentCode: c.enrollmentCode,
    alternateLink: c.alternateLink,
    creationTime: c.creationTime,
  };
}

// Course create / update need scope classroom.courses (re-consent the token if it only has
// classroom.courses.readonly). A teacher-created course comes back PROVISIONED when the domain does not
// let the request set ACTIVE directly; the owner can then activate it with a patch.
export async function createCourse(classroom, { name, section, descriptionHeading, description, room, courseState = "ACTIVE" }) {
  if (!name) throw new Error("name is required");
  const requestBody = { name, ownerId: "me", courseState };
  if (section) requestBody.section = section;
  if (descriptionHeading) requestBody.descriptionHeading = descriptionHeading;
  if (description) requestBody.description = description;
  if (room) requestBody.room = room;
  let res = await classroom.courses.create({ requestBody });
  if (courseState === "ACTIVE" && res.data.courseState !== "ACTIVE") {
    res = await classroom.courses.patch({
      id: res.data.id,
      updateMask: "courseState",
      requestBody: { courseState: "ACTIVE" },
    });
  }
  return summarize(res.data);
}

export async function updateCourse(classroom, courseId, fields) {
  const keys = UPDATABLE.filter((k) => fields[k] !== undefined);
  if (!courseId) throw new Error("courseId is required");
  if (keys.length === 0) throw new Error(`nothing to update (fields: ${UPDATABLE.join(", ")})`);
  const requestBody = Object.fromEntries(keys.map((k) => [k, fields[k]]));
  const res = await classroom.courses.patch({ id: courseId, updateMask: keys.join(","), requestBody });
  return summarize(res.data);
}

// Post an announcement, optionally with the teacher's own Drive files attached
// (materials.driveFile; Classroom itself grants the class view access, so the file needs no sharing).
// state "DRAFT" = invisible to students until a teacher posts it from the course page.
export async function createAnnouncement(classroom, courseId, text, driveFileIds = [], state = "PUBLISHED") {
  if (!courseId || !text) throw new Error("courseId and text are required");
  const requestBody = { text, state };
  if (driveFileIds.length) {
    requestBody.materials = driveFileIds.map((id) => ({ driveFile: { driveFile: { id }, shareMode: "VIEW" } }));
  }
  const res = await classroom.courses.announcements.create({ courseId, requestBody });
  const a = res.data;
  return {
    id: a.id, state: a.state, text: a.text, alternateLink: a.alternateLink, creationTime: a.creationTime,
    attachments: (a.materials || []).map((m) => m.driveFile?.driveFile?.title || Object.keys(m)[0]),
  };
}

// Read a posted announcement back and compare it with the draft, so "the post matches the draft" is a machine
// comparison, not a look (conventions/google-classroom-api.md#readback-after-post). The draft's trailing whitespace is
// ignored (the CLI trims it before posting). Attachments are compared by Drive file id. On a text mismatch,
// firstDiff is the first differing character index and around shows ~30 characters of each side there.
export async function checkAnnouncement(classroom, courseId, announcementId, text, driveFileIds = []) {
  if (!courseId || !announcementId || typeof text !== "string") throw new Error("courseId, announcementId and text are required");
  const res = await classroom.courses.announcements.get({ courseId, id: announcementId });
  const a = res.data;
  const want = text.replace(/\s+$/, "");
  const got = a.text || "";
  let firstDiff = -1;
  if (got !== want) {
    firstDiff = Math.min(got.length, want.length);
    for (let i = 0; i < Math.min(got.length, want.length); i++) {
      if (got[i] !== want[i]) { firstDiff = i; break; }
    }
  }
  const attachedIds = (a.materials || []).map((m) => m.driveFile?.driveFile?.id).filter(Boolean);
  const missingFiles = driveFileIds.filter((id) => !attachedIds.includes(id));
  const extraFiles = attachedIds.filter((id) => !driveFileIds.includes(id));
  const out = {
    ok: got === want && missingFiles.length === 0 && extraFiles.length === 0,
    id: a.id, state: a.state, textMatch: got === want, length: { posted: got.length, draft: want.length },
    attachments: (a.materials || []).map((m) => m.driveFile?.driveFile?.title || Object.keys(m)[0]),
    missingFiles, extraFiles,
  };
  if (firstDiff >= 0) {
    const s = Math.max(0, firstDiff - 10);
    out.firstDiff = firstDiff;
    out.around = { posted: got.slice(s, firstDiff + 20), draft: want.slice(s, firstDiff + 20) };
  }
  return out;
}

// Run fn over items with a few calls in flight, keeping results in input order.
async function inParallel(items, concurrency, fn) {
  const results = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const i = next++;
      results[i] = await fn(items[i]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, worker));
  return results;
}

// Invite members. Teachers cannot add students directly (courses.students.create is for
// domain admins and self-enrolment), so this goes through invitations: Google e-mails each
// invitee and they join on accept. userId may be an e-mail or a numeric Classroom user id
// (reusing the id seen in another course avoids guessing which of a person's addresses
// holds their Classroom account). Needs scope classroom.rosters.
// One API call per invitee: sequential took minutes for ~100 people (実測) → a few calls in parallel.
export async function inviteMembers(classroom, courseId, userIds, role = "STUDENT", concurrency = 6) {
  if (!courseId) throw new Error("courseId is required");
  if (!["STUDENT", "TEACHER"].includes(role)) throw new Error("role must be STUDENT or TEACHER");
  return inParallel(userIds, concurrency, async (userId) => {
    try {
      const res = await classroom.invitations.create({ requestBody: { courseId, userId, role } });
      return { userId, status: "invited", invitationId: res.data.id };
    } catch (err) {
      const e = err?.response?.data?.error;
      return { userId, status: e?.status === "ALREADY_EXISTS" ? "already" : "error", message: e?.message || err.message };
    }
  });
}

const isNotFound = (err) => err?.response?.status === 404 || err?.code === 404 || err?.status === 404;

// Where each roster address stands in a course: joined / invited (pending) / missing. The student list
// carries no e-mail without scope classroom.profile.emails, so the match goes the other way: pass the
// address as userId to students.get (404 = not joined) and invitations.list (both accept an e-mail).
// 2 calls per address → a few in parallel, like inviteMembers. Also returns the joined students the
// roster does not account for (teaching assistants, auditors, people who joined by class code), by name.
export async function rosterStatus(classroom, courseId, emails, concurrency = 6) {
  if (!courseId) throw new Error("courseId is required");
  const rows = await inParallel(emails, concurrency, async (email) => {
    try {
      const st = await classroom.courses.students.get({ courseId, userId: email })
        .catch((err) => (isNotFound(err) ? null : Promise.reject(err)));
      if (st) return { email, status: "joined", userId: st.data.userId };
      const inv = await classroom.invitations.list({ courseId, userId: email });
      return { email, status: (inv.data.invitations || []).length ? "invited" : "missing" };
    } catch (err) {
      return { email, status: "error", message: err?.response?.data?.error?.message || err.message };
    }
  });
  const joinedIds = new Set(rows.filter((r) => r.status === "joined").map((r) => r.userId));
  const all = [];
  let pageToken;
  do {
    const res = await classroom.courses.students.list({ courseId, pageSize: 100, pageToken });
    all.push(...(res.data.students || []));
    pageToken = res.data.nextPageToken;
  } while (pageToken);
  const notInRoster = all.filter((s) => !joinedIds.has(s.userId)).map((s) => s.profile?.name?.fullName || s.userId);
  return { rows, classroomStudents: all.length, notInRoster };
}

// Who set the grades on one assignment, and where the grades stand. Each submission's submissionHistory
// carries gradeHistory entries with actorUserId (the teacher who changed the grade), gradeChangeType
// (draft or assigned grade), pointsEarned and gradeTimestamp; teachers.list turns the actor id into a name.
// Returns counts only, no student names, so the result can be shown in a chat or kept in a note.
// An entry without pointsEarned cannot be told apart between 0 and a cleared grade, so it is counted as
// "none"; the current value is draftGrade / assignedGrade. A submission can hold a grade with no
// grade-history entry at all (seen in practice), so history alone does not attribute every grade.
export async function gradeHistory(classroom, courseId, courseWorkId) {
  if (!courseId || !courseWorkId) throw new Error("courseId and courseWorkId are required");
  const teachers = (await classroom.courses.teachers.list({ courseId })).data.teachers || [];
  const name = Object.fromEntries(teachers.map((t) => [t.userId, t.profile?.name?.fullName || t.userId]));
  const subs = [];
  let pageToken;
  do {
    const res = await classroom.courses.courseWork.studentSubmissions.list({ courseId, courseWorkId, pageSize: 100, pageToken });
    subs.push(...(res.data.studentSubmissions || []));
    pageToken = res.data.nextPageToken;
  } while (pageToken);
  const bump = (o, k) => { o[k] = (o[k] || 0) + 1; };
  const byState = {}, changes = {}, stamps = [];
  let noHistory = 0;
  for (const s of subs) {
    bump(byState, `${s.state} late=${!!s.late} draft=${s.draftGrade ?? "none"} assigned=${s.assignedGrade ?? "none"}`);
    const hist = (s.submissionHistory || []).map((h) => h.gradeHistory).filter(Boolean);
    if (!hist.length && (s.draftGrade != null || s.assignedGrade != null)) noHistory += 1;
    for (const g of hist) {
      const who = name[g.actorUserId] || `not a teacher ${g.actorUserId}`;
      bump(changes, `${who} | ${g.gradeChangeType} | ${g.pointsEarned ?? "none"}`);
      if (g.gradeTimestamp) stamps.push(g.gradeTimestamp);
    }
  }
  stamps.sort();
  return { submissions: subs.length, byState, changes, noHistory, span: stamps.length ? [stamps[0], stamps.at(-1)] : null };
}

// Coursework of a course (id, title, type, state, due date), newest first, to find the id that
// shortAnswers / gradeHistory take. Read-only.
export async function listCourseWork(classroom, courseId) {
  if (!courseId) throw new Error("courseId is required");
  const out = [];
  let pageToken;
  do {
    const res = await classroom.courses.courseWork.list({ courseId, pageSize: 100, pageToken });
    for (const w of res.data.courseWork || []) {
      const d = w.dueDate;
      out.push({ id: w.id, title: w.title, workType: w.workType, state: w.state, creationTime: w.creationTime,
        due: d ? `${d.year}-${String(d.month).padStart(2, "0")}-${String(d.day).padStart(2, "0")}` : null });
    }
    pageToken = res.data.nextPageToken;
  } while (pageToken);
  return out.sort((a, b) => String(b.creationTime).localeCompare(String(a.creationTime)));
}

// Read one coursework and compare its publication settings with an explicit expected record.
// Only final line breaks are ignored in descriptions; spaces and internal newlines still matter.
// dueAt must include a timezone, or be null for no deadline; maxPoints null means ungraded.
// This is GET-only. UI-only settings (such as the late-submission lock) remain unverified.
export async function checkCourseWork(classroom, courseId, courseWorkId, expected) {
  if (!courseId || !courseWorkId) throw new Error("courseId and courseWorkId are required");
  if (!expected || typeof expected.title !== "string" || typeof expected.description !== "string") {
    throw new Error("expected title and description are required");
  }
  if (expected.maxPoints !== null && (!Number.isFinite(expected.maxPoints) || expected.maxPoints < 0)) {
    throw new Error("expected maxPoints must be a nonnegative number or null");
  }
  if (expected.dueAt !== null && (typeof expected.dueAt !== "string" ||
      !/T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(expected.dueAt) ||
      !Number.isFinite(Date.parse(expected.dueAt)))) {
    throw new Error("expected dueAt must have an explicit timezone, or be null");
  }
  const { data: w } = await classroom.courses.courseWork.get({ courseId, id: courseWorkId });
  const d = w.dueDate;
  const t = w.dueTime || {};
  const dueAt = d ? new Date(Date.UTC(d.year, d.month - 1, d.day,
    t.hours || 0, t.minutes || 0, t.seconds || 0, (t.nanos || 0) / 1e6)).toISOString() : null;
  const posted = {
    id: w.id, title: w.title, description: w.description || "", state: w.state,
    workType: w.workType, maxPoints: w.maxPoints ?? null, dueAt,
    alternateLink: w.alternateLink, creationTime: w.creationTime, updateTime: w.updateTime,
  };
  const stripFinalNewlines = (s) => s.replace(/(?:\r?\n)+$/, "");
  const got = stripFinalNewlines(posted.description);
  const want = stripFinalNewlines(expected.description);
  const checks = {
    title: posted.title === expected.title,
    description: got === want,
    state: posted.state === (expected.state ?? "PUBLISHED"),
    maxPoints: posted.maxPoints === expected.maxPoints,
    dueAt: dueAt === (expected.dueAt === null ? null : new Date(expected.dueAt).toISOString()),
  };
  if (expected.workType !== undefined) checks.workType = posted.workType === expected.workType;
  const result = {
    ok: Object.values(checks).every(Boolean), checks, posted,
    unverified: ["lateSubmissionLock"],
  };
  if (!checks.description) {
    let index = 0;
    while (index < Math.min(got.length, want.length) && got[index] === want[index]) index++;
    const start = Math.max(0, index - 10);
    result.descriptionDifference = {
      index, posted: got.slice(start, index + 20), expected: want.slice(start, index + 20),
    };
  }
  return result;
}

// Short-answer texts of a coursework without names or user ids, one entry per submission, for counting
// answers by theme (scripts/short-answer-themes.py reads this array). A submission that is not turned in
// (CREATED / RECLAIMED_BY_STUDENT) gives "", so the length is the number of students the work is assigned
// to and the non-empty entries are the answers. Read-only.
export async function shortAnswers(classroom, courseId, courseWorkId) {
  if (!courseId || !courseWorkId) throw new Error("courseId and courseWorkId are required");
  const out = [];
  let pageToken;
  do {
    const res = await classroom.courses.courseWork.studentSubmissions.list({ courseId, courseWorkId, pageSize: 100, pageToken });
    for (const s of res.data.studentSubmissions || []) {
      const done = s.state === "TURNED_IN" || s.state === "RETURNED";
      out.push(done ? (s.shortAnswerSubmission?.answer ?? "") : "");
    }
    pageToken = res.data.nextPageToken;
  } while (pageToken);
  return out;
}

// Addresses from a roster CSV whose last column is the e-mail (header row skipped, quotes stripped,
// rows without "@" dropped). Matches the course roster files the registrar's system exports.
export function emailsFromRosterText(text) {
  return text.split(/\r?\n/).filter(Boolean).slice(1)
    .map((l) => l.split(",").pop().replace(/"/g, "").trim())
    .filter((u) => u.includes("@"));
}
