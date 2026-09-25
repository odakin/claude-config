// Google Classroom course engine: create / update, invite (parallel), announcements, roster match by address; takes a googleapis classroom client, no imports.
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

// Addresses from a roster CSV whose last column is the e-mail (header row skipped, quotes stripped,
// rows without "@" dropped). Matches the course roster files the registrar's system exports.
export function emailsFromRosterText(text) {
  return text.split(/\r?\n/).filter(Boolean).slice(1)
    .map((l) => l.split(",").pop().replace(/"/g, "").trim())
    .filter((u) => u.includes("@"));
}
