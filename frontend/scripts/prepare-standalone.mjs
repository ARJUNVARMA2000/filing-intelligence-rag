import { cpSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const standaloneRoot = join(".next", "standalone");
const standaloneNext = join(standaloneRoot, ".next");

if (!existsSync(standaloneRoot)) {
  throw new Error("Next.js standalone output was not generated.");
}

mkdirSync(standaloneNext, { recursive: true });
cpSync(join(".next", "static"), join(standaloneNext, "static"), { recursive: true });
if (existsSync("public")) cpSync("public", join(standaloneRoot, "public"), { recursive: true });
