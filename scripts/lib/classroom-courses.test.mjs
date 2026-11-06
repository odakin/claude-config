// Hermetic self-test for classroom-courses.mjs; uses a fake Classroom client and needs no network or googleapis.
import assert from "node:assert/strict";
import {
  summarize, createCourse, updateCourse, createAnnouncement, checkAnnouncement, inviteMembers, rosterStatus, emailsFromRosterText,
  gradeHistory, shortAnswers, listCourseWork,
} from "./classroom-courses.mjs";

const apiError = (status, code) => Object.assign(new Error(status), { code, response: { status: code, data: { error: { status, message: status } } } });

// Fake course: a.example joined (u1), b.example has a pending invitation, c.example nothing,
// err.example makes students.get fail with a non-404 error; u9 joined but is on no roster.
function fakeClient({ createdState = "ACTIVE" } = {}) {
  const calls = [];
  const students = { "a@example.com": "u1", u9: "u9" };
  const invited = new Set(["b@example.com"]);
  return {
    calls,
    courses: {
      create: async ({ requestBody }) => { calls.push(["create", requestBody]); return { data: { id: "c1", ...requestBody, courseState: createdState } }; },
      patch: async (req) => { calls.push(["patch", req]); return { data: { id: req.id, ...req.requestBody } }; },
      announcements: {
        create: async ({ courseId, requestBody }) => ({ data: { id: "a1", courseId, ...requestBody, materials: (requestBody.materials || []).map((m) => ({ driveFile: { driveFile: { title: `t-${m.driveFile.driveFile.id}` } } })) } }),
        get: async ({ id }) => ({ data: { id, state: "PUBLISHED", text: "line one\n・項目 ∂S/∂U", materials: [{ driveFile: { driveFile: { id: "f1", title: "handout.pdf" } } }] } }),
      },
      students: {
        get: async ({ userId }) => {
          if (userId === "err@example.com") throw apiError("INTERNAL", 500);
          if (!students[userId]) throw apiError("NOT_FOUND", 404);
          return { data: { userId: students[userId] } };
        },
        list: async ({ pageToken }) => (pageToken
          ? { data: { students: [{ userId: "u9", profile: { name: { fullName: "Helper Nine" } } }] } }
          : { data: { students: [{ userId: "u1", profile: { name: { fullName: "Student One" } } }], nextPageToken: "p2" } }),
      },
    },
    invitations: {
      create: async ({ requestBody }) => {
        await new Promise((r) => setTimeout(r, requestBody.userId.length % 3));
        if (requestBody.userId === "dup@example.com") throw apiError("ALREADY_EXISTS", 409);
        if (requestBody.userId === "bad@example.com") throw apiError("PERMISSION_DENIED", 403);
        return { data: { id: `inv-${requestBody.userId}` } };
      },
      list: async ({ userId }) => ({ data: { invitations: invited.has(userId) ? [{ id: "i1" }] : [] } }),
    },
  };
}

let n = 0;
const check = async (name, fn) => { await fn(); n += 1; console.log(`PASS ${name}`); };

await check("summarize picks the listed fields", () => {
  assert.deepEqual(Object.keys(summarize({ id: "1", name: "n", extra: 1 })).sort(),
    ["alternateLink", "creationTime", "enrollmentCode", "id", "name", "room", "section", "state"].sort());
});

await check("createCourse activates a PROVISIONED course with a patch", async () => {
  const c = fakeClient({ createdState: "PROVISIONED" });
  const r = await createCourse(c, { name: "Course", section: "S" });
  assert.equal(r.state, "ACTIVE");
  assert.deepEqual(c.calls.map((x) => x[0]), ["create", "patch"]);
  assert.equal(c.calls[1][1].updateMask, "courseState");
});

await check("createCourse does not patch when already ACTIVE, and needs a name", async () => {
  const c = fakeClient();
  await createCourse(c, { name: "Course" });
  assert.deepEqual(c.calls.map((x) => x[0]), ["create"]);
  await assert.rejects(createCourse(c, {}), /name is required/);
});

await check("updateCourse sends only the given updatable fields as the mask", async () => {
  const c = fakeClient();
  await updateCourse(c, "c1", { courseState: "ARCHIVED", bogus: 1, name: undefined });
  assert.equal(c.calls[0][1].updateMask, "courseState");
  await assert.rejects(updateCourse(c, "c1", {}), /nothing to update/);
});

await check("createAnnouncement attaches Drive files and keeps the state", async () => {
  const r = await createAnnouncement(fakeClient(), "c1", "hello", ["f1", "f2"], "DRAFT");
  assert.equal(r.state, "DRAFT");
  assert.deepEqual(r.attachments, ["t-f1", "t-f2"]);
});

await check("checkAnnouncement matches the draft exactly, ignoring the draft's trailing newline", async () => {
  const r = await checkAnnouncement(fakeClient(), "c1", "a9", "line one\n・項目 ∂S/∂U\n\n", ["f1"]);
  assert.equal(r.ok, true);
  assert.equal(r.textMatch, true);
  assert.deepEqual(r.attachments, ["handout.pdf"]);
  assert.equal(r.firstDiff, undefined);
});

await check("checkAnnouncement reports the first differing character and attachment differences", async () => {
  const r = await checkAnnouncement(fakeClient(), "c1", "a9", "line one\n・項目 ∂S/∂V", ["f2"]);
  assert.equal(r.ok, false);
  assert.equal(r.textMatch, false);
  assert.equal(r.firstDiff, "line one\n・項目 ∂S/∂".length);
  assert.deepEqual(r.missingFiles, ["f2"]);
  assert.deepEqual(r.extraFiles, ["f1"]);
  const short = await checkAnnouncement(fakeClient(), "c1", "a9", "line one", ["f1"]);
  assert.equal(short.firstDiff, "line one".length);  // posted text is longer than the draft
  await assert.rejects(checkAnnouncement(fakeClient(), "c1", "", "x"), /required/);
});

await check("inviteMembers keeps input order and tallies already / error", async () => {
  const users = ["a@example.com", "dup@example.com", "longer-name@example.com", "bad@example.com", "b@example.com"];
  const r = await inviteMembers(fakeClient(), "c1", users, "STUDENT", 3);
  assert.deepEqual(r.map((x) => x.userId), users);
  assert.deepEqual(r.map((x) => x.status), ["invited", "already", "invited", "error", "invited"]);
  await assert.rejects(inviteMembers(fakeClient(), "c1", users, "OWNER"), /role must be/);
});

await check("rosterStatus classifies joined / invited / missing / error and finds joiners off the roster", async () => {
  const emails = ["a@example.com", "b@example.com", "c@example.com", "err@example.com"];
  const s = await rosterStatus(fakeClient(), "c1", emails, 2);
  assert.deepEqual(s.rows.map((r) => r.status), ["joined", "invited", "missing", "error"]);
  assert.equal(s.classroomStudents, 2);
  assert.deepEqual(s.notInRoster, ["Helper Nine"]);
});

await check("gradeHistory counts grade changes by teacher and flags grades without history", async () => {
  const sub = (state, draftGrade, hist) => ({
    state, draftGrade,
    submissionHistory: [{ stateHistory: { state: "CREATED" } },
      ...hist.map(([actorUserId, pointsEarned, gradeTimestamp]) => ({ gradeHistory: { actorUserId, pointsEarned, gradeTimestamp, gradeChangeType: "DRAFT_GRADE_POINTS_EARNED_CHANGE" } }))],
  });
  const pages = [
    { studentSubmissions: [sub("TURNED_IN", 5, [["t1", 5, "2030-01-02T00:00:00Z"]]), sub("CREATED", 0, [])], nextPageToken: "p2" },
    { studentSubmissions: [sub("TURNED_IN", 5, [["t1", 5, "2030-01-01T00:00:00Z"]]), sub("CREATED", undefined, [["t1", undefined, "2030-01-03T00:00:00Z"]])] },
  ];
  const c = { courses: {
    teachers: { list: async () => ({ data: { teachers: [{ userId: "t1", profile: { name: { fullName: "Teacher A" } } }] } }) },
    courseWork: { studentSubmissions: { list: async ({ pageToken }) => ({ data: pages[pageToken ? 1 : 0] }) } },
  } };
  const r = await gradeHistory(c, "c1", "w1");
  assert.equal(r.submissions, 4);
  assert.equal(r.changes["Teacher A | DRAFT_GRADE_POINTS_EARNED_CHANGE | 5"], 2);
  assert.equal(r.changes["Teacher A | DRAFT_GRADE_POINTS_EARNED_CHANGE | none"], 1);
  assert.equal(r.noHistory, 1);
  assert.deepEqual(r.span, ["2030-01-01T00:00:00Z", "2030-01-03T00:00:00Z"]);
  assert.equal(r.byState["TURNED_IN late=false draft=5 assigned=none"], 2);
  await assert.rejects(gradeHistory(c, "c1"), /courseWorkId are required/);
});

await check("shortAnswers gives one string per submission across pages, \"\" when not turned in, and no user ids", async () => {
  const pages = [
    { studentSubmissions: [
      { userId: "s1", state: "TURNED_IN", shortAnswerSubmission: { answer: "answer one" } },
      { userId: "s2", state: "CREATED", shortAnswerSubmission: { answer: "draft not turned in" } },
      { userId: "s3", state: "CREATED" }], nextPageToken: "p2" },
    { studentSubmissions: [
      { userId: "s4", state: "RETURNED", shortAnswerSubmission: { answer: "answer two" } },
      { userId: "s5", state: "RECLAIMED_BY_STUDENT", shortAnswerSubmission: { answer: "taken back" } },
      { userId: "s6", state: "TURNED_IN" }] },
  ];
  const c = { courses: { courseWork: { studentSubmissions: { list: async ({ pageToken }) => ({ data: pages[pageToken ? 1 : 0] }) } } } };
  const r = await shortAnswers(c, "c1", "w1");
  assert.deepEqual(r, ["answer one", "", "", "answer two", "", ""]);
  assert.ok(!JSON.stringify(r).includes("s1"));
  await assert.rejects(shortAnswers(c, "c1"), /courseWorkId are required/);
});

await check("listCourseWork pages through, formats the due date and sorts newest first", async () => {
  const pages = [
    { courseWork: [{ id: "w1", title: "Week 1", workType: "SHORT_ANSWER_QUESTION", state: "PUBLISHED", creationTime: "2030-01-01T00:00:00Z", dueDate: { year: 2030, month: 1, day: 8 } }], nextPageToken: "p2" },
    { courseWork: [{ id: "w2", title: "Week 2", workType: "ASSIGNMENT", state: "DRAFT", creationTime: "2030-01-09T00:00:00Z" }] },
  ];
  const c = { courses: { courseWork: { list: async ({ pageToken }) => ({ data: pages[pageToken ? 1 : 0] }) } } };
  const r = await listCourseWork(c, "c1");
  assert.deepEqual(r.map((w) => [w.id, w.due]), [["w2", null], ["w1", "2030-01-08"]]);
  await assert.rejects(listCourseWork(c), /courseId is required/);
});

await check("emailsFromRosterText takes the last column, skips the header and non-addresses", () => {
  const text = '"year","id","name","E-mail"\r\n"2026","S1","A","a@example.com"\r\n"2026","S2","B",""\r\n"2026","S3","C","c@example.com"\r\n';
  assert.deepEqual(emailsFromRosterText(text), ["a@example.com", "c@example.com"]);
});

console.log(`classroom-courses selftest: ${n} passed`);
