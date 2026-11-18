// Drives a pubdeploy machine (its JSON, argv[2]) with XState v5 through a script of
// events (argv[3]), and prints each region's state after the start and after each event.
import { readFileSync } from "node:fs";
import { createActor, createMachine } from "xstate";

const machine = JSON.parse(readFileSync(process.argv[2], "utf8"));
const script = JSON.parse(readFileSync(process.argv[3], "utf8"));
const guards = {
  is_ready: ({ event }) => event.state === "ready",
  is_found: ({ event }) => event.state === "missing" || event.state === "drift",
  is_ok: ({ event }) => event.ok === true,
};
const actor = createActor(createMachine(machine).provide({ guards }));
const seen = [];
const regions = () => Object.fromEntries(Object.entries(actor.getSnapshot().value.running).sort());
actor.start();
seen.push(regions());
for (const event of script) {
  actor.send(event);
  seen.push(regions());
}
process.stdout.write(JSON.stringify(seen));
