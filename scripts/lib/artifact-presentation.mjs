// Shared @oai/artifact-tool presentation builder: editable primitives, notes, finalization, and page renders.
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

export async function loadArtifactPresentationRuntime(nodeModules) {
  if (!path.isAbsolute(nodeModules ?? "")) {
    throw new Error("nodeModules must be an absolute bundled Node package directory");
  }
  const runtimeRequire = createRequire(path.join(nodeModules, "package.json"));
  return import(pathToFileURL(runtimeRequire.resolve("@oai/artifact-tool")).href);
}

function imageContentType(filename) {
  const extension = path.extname(filename).toLowerCase();
  if (extension === ".jpg" || extension === ".jpeg") return "image/jpeg";
  if (extension === ".webp") return "image/webp";
  if (extension === ".svg") return "image/svg+xml";
  return "image/png";
}

export function createPresentationKit({
  Presentation,
  width,
  height,
  assetDir,
  titleFont,
  bodyFont,
  ink = "#53585F",
  background = "#FFFFFF",
  titlePosition = { left: 100, top: 45, width: 1740, height: 140 },
  subtitlePosition = { left: 100, top: 192, width: 1740, height: 90 },
  titleSize = 94,
  subtitleSize = 53,
}) {
  if (!Presentation || !path.isAbsolute(assetDir ?? "")) {
    throw new Error("Presentation and an absolute assetDir are required");
  }
  const presentation = Presentation.create({ slideSize: { width, height } });
  const notes = [];

  function text(
    slide,
    value,
    left,
    top,
    boxWidth,
    boxHeight,
    fontSize = 58,
    { font = bodyFont, color = ink, bold = false, align = "left" } = {},
  ) {
    const shape = slide.shapes.add({
      geometry: "textbox",
      position: { left, top, width: boxWidth, height: boxHeight },
      fill: "none",
      line: { fill: "none", width: 0 },
    });
    shape.text = value;
    shape.text.style = {
      typeface: font,
      fontSize,
      color,
      bold,
      alignment: align,
      verticalAlignment: "top",
      autoFit: "none",
      wrap: "none",
      insets: { left: 0, right: 0, top: 0, bottom: 0 },
    };
    return shape;
  }

  function slide(title, subtitle = "") {
    const item = presentation.slides.add();
    item.background.fill = background;
    if (title) {
      text(item, title, titlePosition.left, titlePosition.top, titlePosition.width,
        titlePosition.height, titleSize, { font: titleFont });
    }
    if (subtitle) {
      text(item, subtitle, subtitlePosition.left, subtitlePosition.top,
        subtitlePosition.width, subtitlePosition.height, subtitleSize, { font: titleFont });
    }
    return item;
  }

  async function image(slideItem, filename, left, top, imageWidth, imageHeight,
    fit = "contain", alt = filename) {
    return slideItem.images.add({
      blob: new Uint8Array(await fs.readFile(path.join(assetDir, filename))),
      contentType: imageContentType(filename),
      alt,
      fit,
      position: { left, top, width: imageWidth, height: imageHeight },
    });
  }

  function footer(slideItem, number) {
    return text(slideItem, String(number), width - 130, height - 70, 70, 44, 28,
      { align: "right", color: "#888888" });
  }

  function note(slideItem, number, body, sources = "") {
    slideItem.speakerNotes.textFrame.setText(
      body + (sources ? `\n\n出典\n${sources}` : ""),
    );
    notes.push(`## ${number}\n\n${body}\n\n${sources ? `出典: ${sources}\n` : ""}`);
  }

  function rich(slideItem, value, emphasized, left, top, boxWidth, boxHeight, fontSize = 62) {
    const shape = text(slideItem, value, left, top, boxWidth, boxHeight, fontSize);
    for (const phrase of emphasized) shape.text.get(phrase).bold = true;
    return shape;
  }

  function link(slideItem, label, uri, left, top, boxWidth, boxHeight, fontSize = 42) {
    const shape = text(slideItem, label, left, top, boxWidth, boxHeight, fontSize);
    shape.text.get(label).link = { uri, isExternal: true };
    return shape;
  }

  return { presentation, notes, slide, text, image, footer, note, rich, link };
}

export async function finalizePresentationBuild({
  PresentationFile,
  presentation,
  notes,
  notesTitle,
  workspaceDir,
  finalPath,
  outputStem,
  presentationsSkillDir,
  pythonExecutable,
  expectedSlideSizeEmu,
  explicitTotalSlideCount,
  fontPolicy,
  renderScale = 0.7,
}) {
  for (const [label, value] of Object.entries({
    workspaceDir,
    finalPath,
    presentationsSkillDir,
    pythonExecutable,
  })) {
    if (!path.isAbsolute(value ?? "")) throw new Error(`${label} must be absolute`);
  }
  const buildDir = path.join(workspaceDir, "build");
  await fs.mkdir(buildDir, { recursive: true });
  await fs.mkdir(path.dirname(finalPath), { recursive: true });
  const { finalizePresentation } = await import(pathToFileURL(path.join(
    presentationsSkillDir,
    "container_tools/artifact_tool_utils.mjs",
  )).href);
  const candidatePath = path.join(buildDir, `${outputStem}.candidate.pptx`);
  const receiptPath = path.join(buildDir, `${outputStem}.validation.json`);
  await (await PresentationFile.exportPptx(presentation)).save(candidatePath);
  await fs.writeFile(
    path.join(buildDir, `${outputStem}.speaker-notes.md`),
    `# ${notesTitle}\n\n${notes.join("\n")}`,
  );
  const inspection = await presentation.inspect({
    kind: "slide,textbox,image,notes",
    maxChars: 200000,
  });
  await fs.writeFile(path.join(buildDir, `${outputStem}.inspection.ndjson`), inspection.ndjson);
  const result = await finalizePresentation({
    workspaceDir,
    candidatePath,
    finalPath,
    pythonExecutable,
    integrityValidatorPath: path.join(
      presentationsSkillDir,
      "container_tools/inspect_presentation_package_integrity.py",
    ),
    layoutValidatorPath: path.join(
      presentationsSkillDir,
      "container_tools/inspect_presentation_layout_geometry.py",
    ),
    layoutArgs: ["--expected-slide-size-emu", expectedSlideSizeEmu, "--validate-heading-fit"],
    requiredNativeTableOwnerSlides: [],
    requiredNativeChartOwnerSlides: [],
    explicitTotalSlideCount,
    fontPolicy,
    verifyArtifactToolImport: true,
    receiptPath,
  });
  for (let index = 0; index < presentation.slides.items.length; index += 1) {
    const png = await presentation.export({
      slide: presentation.slides.items[index],
      format: "png",
      scale: renderScale,
    });
    await fs.writeFile(
      path.join(buildDir, `${outputStem}.slide-${String(index + 1).padStart(2, "0")}.png`),
      new Uint8Array(await png.arrayBuffer()),
    );
  }
  return result;
}
