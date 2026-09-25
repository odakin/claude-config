// Hermetic self-test for classroom-courses.mjs; uses a fake Classroom client and needs no network or googleapis.
import assert from "node:assert/strict";
import {
  summarize, createCourse, updateCourse, createAnnouncement, inviteMembers, rosterStatus, emailsFromRosterText,
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

await check("emailsFromRosterText takes the last column, skips the header and non-addresses", () => {
  const text = '"year","id","name","E-mail"\r\n"2026","S1","A","a@example.com"\r\n"2026","S2","B",""\r\n"2026","S3","C","c@example.com"\r\n';
  assert.deepEqual(emailsFromRosterText(text), ["a@example.com", "c@example.com"]);
});

console.log(`classroom-courses selftest: ${n} passed`);
