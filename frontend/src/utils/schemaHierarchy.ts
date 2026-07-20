import type { Field } from '../types';
import FORM_SCHEMA, { getAllFields, getMutuallyExclusiveGroups } from '../../../form_schema';

// ─────────────────────────────────────────────────────────────────────────────
// Schema-driven hierarchy resolver.
//
// The review UI needs `parent_label` / `field_type` to group checkbox/radio
// options under a single question. The backend computes this in enrich_fields()
// but it is stripped from the persisted result, so older (and current) API
// payloads may carry null metadata. This module re-derives the same hierarchy
// from the single-source-of-truth form schema so grouping is always correct,
// regardless of what the payload contains.
// ─────────────────────────────────────────────────────────────────────────────

const SCHEMA_FIELDS = getAllFields(FORM_SCHEMA);
const SCHEMA_BY_LABEL = new Map<string, typeof SCHEMA_FIELDS[number]>();
for (const sf of SCHEMA_FIELDS) SCHEMA_BY_LABEL.set(sf.label, sf);

// Labels of every field that is a group parent (something points at it via parent_label).
const PARENT_LABELS = new Map<string, string>(); // childLabel -> parentLabel
const TABLE_HEADERS = new Map<string, string>();  // tableRowLabel -> headerLabel
for (const sf of SCHEMA_FIELDS) {
  if (sf.parent_label) PARENT_LABELS.set(sf.label, sf.parent_label);
  if (sf.tableHeaderLabel) TABLE_HEADERS.set(sf.label, sf.tableHeaderLabel);
}

// Mutually-exclusive (Yes/No, radio) groups that use isYesNoPair / mutuallyExclusiveWith
// instead of parent_label — e.g. "4.3 Do you own...? — Yes/No".
const MUTEX_GROUPS: string[][] = getMutuallyExclusiveGroups(FORM_SCHEMA);
const MUTEX_MEMBERS = new Map<string, string[]>(); // memberLabel -> group labels
for (const group of MUTEX_GROUPS) {
  for (const label of group) MUTEX_MEMBERS.set(label, group);
}

// Pre-computed list of known parent labels (for quick membership checks).
// Includes mutex (Yes/No) group stems so the UI can group those options too.
const PARENT_LABEL_SET = new Set<string>(PARENT_LABELS.values());
for (const group of MUTEX_GROUPS) {
  const stem = commonPrefix(group);
  if (stem) PARENT_LABEL_SET.add(stem);
}

// Mutex groups indexed by their stem (the question label), e.g.
// "3.1 House Ownership" -> ["3.1 House Ownership — Own", "3.1 House Ownership — Rented"].
const MUTEX_GROUPS_BY_STEM = new Map<string, string[]>();
for (const group of MUTEX_GROUPS) {
  const stem = commonPrefix(group);
  if (stem) MUTEX_GROUPS_BY_STEM.set(stem, group);
}

// Strip the question stem prefix from a member label to get the option display name.
export function mutexOptionName(memberLabel: string, stem: string): string {
  for (const sep of [' — ', ' - ', ' – ']) {
    if (memberLabel.startsWith(stem + sep)) {
      return memberLabel.slice((stem + sep).length);
    }
  }
  const parts = memberLabel.split(/ — | - | – /);
  return parts.slice(1).join(' — ') || memberLabel;
}

// If `label` is a mutex-group member, return the group stem and all member labels.
export function mutexGroupFor(label: string): { stem: string; members: string[] } | null {
  const members = MUTEX_MEMBERS.get(label);
  if (!members || members.length === 0) return null;
  const stem = commonPrefix(members);
  if (!stem) return null;
  return { stem, members };
}

// If `label` IS a mutex group stem, return its member labels; else null.
export function mutexMembersOfStem(stem: string): string[] | null {
  return MUTEX_GROUPS_BY_STEM.get(stem) ?? null;
}

// Unified map of ALL single-select radio groups (stem -> member labels), covering
// both mutex (mutuallyExclusiveWith) groups AND parent_label-based radio groups
// (e.g. 3.2 Type of Home, 3.3 Type of Ceiling). Used to collapse a group into a
// single 8.2-style radio row and to derive its option names.
const RADIO_GROUPS_BY_STEM = new Map<string, string[]>();
for (const group of MUTEX_GROUPS) {
  const stem = commonPrefix(group);
  if (stem && !RADIO_GROUPS_BY_STEM.has(stem)) RADIO_GROUPS_BY_STEM.set(stem, group);
}
for (const sf of SCHEMA_FIELDS) {
  if (!sf.parent_label) continue;
  const parent = SCHEMA_BY_LABEL.get(sf.parent_label);
  const ptype = parent?.type;
  // Single-select radio group when the parent is a radio. Only include actual radio
  // options as members — exclude "specify" follow-up children (e.g. 3.2 Others (specify)).
  if (ptype === 'radio' && sf.type === 'radio') {
    if (!RADIO_GROUPS_BY_STEM.has(sf.parent_label)) {
      RADIO_GROUPS_BY_STEM.set(sf.parent_label, []);
    }
    const arr = RADIO_GROUPS_BY_STEM.get(sf.parent_label)!;
    if (!arr.includes(sf.label)) arr.push(sf.label);
  }
}

// If `label` IS a single-select radio group stem, return its member labels; else null.
export function radioGroupChildrenOf(stem: string): string[] | null {
  return RADIO_GROUPS_BY_STEM.get(stem) ?? null;
}

// Loose-field fallback: match a label prefix to a known parent label.
// Handles children emitted by the LLM that don't perfectly match a schema label
// but share a known parent prefix (e.g. "4.1 Assets at Home(tick all that apply) - X").
function looseParentFor(label: string): string | null {
  for (const parent of PARENT_LABEL_SET) {
    if (label === parent) continue;
    for (const sep of [' — ', ' - ', ' – ']) {
      if (label.startsWith(parent + sep)) return parent;
    }
  }
  return null;
}

function resolveParentLabel(f: Field): string | null | undefined {
  // 1. Trust served metadata when present.
  if (f.parent_label) return f.parent_label;
  // 2. Schema lookup.
  const sf = SCHEMA_BY_LABEL.get(f.label);
  if (sf?.parent_label) return sf.parent_label;
  if (sf?.tableHeaderLabel) return sf.tableHeaderLabel;
  // 3. Mutually-exclusive group membership (Yes/No pairs).
  const mutex = MUTEX_MEMBERS.get(f.label);
  if (mutex && mutex.length > 0) {
    // Use the longest common prefix of the group as the "parent" question label.
    return commonPrefix(mutex);
  }
  // 4. Loose prefix match.
  return looseParentFor(f.label);
}

function resolveFieldType(f: Field): string | null | undefined {
  if (f.field_type) return f.field_type;
  const sf = SCHEMA_BY_LABEL.get(f.label);
  if (!sf) {
    // Best-effort guess for loose fields.
    if (MUTEX_MEMBERS.has(f.label)) return 'radio';
    return null;
  }
  return sf.type;
}

function commonPrefix(labels: string[]): string {
  if (labels.length === 0) return '';
  let prefix = labels[0];
  for (const l of labels.slice(1)) {
    let i = 0;
    while (i < prefix.length && i < l.length && prefix[i] === l[i]) i++;
    prefix = prefix.slice(0, i);
  }
  // Trim back to the last separator so the prefix reads like the question stem.
  const lastSep = Math.max(prefix.lastIndexOf(' — '), prefix.lastIndexOf(' - '), prefix.lastIndexOf(' – '));
  return lastSep > 0 ? prefix.slice(0, lastSep) : prefix;
}

/**
 * Returns a new field array with `parent_label` / `field_type` resolved from the
 * schema. Cheap (memoize the result per job in the caller).
 */
export function resolveHierarchy(fields: Field[]): Field[] {
  return fields.map(f => {
    const parent_label = resolveParentLabel(f);
    const field_type = resolveFieldType(f);
    const sf = SCHEMA_BY_LABEL.get(f.label);
    const parent_option_label = sf?.parentOptionLabel ?? null;
    if (
      parent_label === f.parent_label &&
      field_type === f.field_type &&
      parent_option_label === (f.parent_option_label ?? null)
    ) return f;
    return {
      ...f,
      parent_label: parent_label ?? null,
      field_type: field_type ?? null,
      parent_option_label: parent_option_label ?? null,
    };
  });
}

/** Schema field type for a label (used to synthesize group headers for parents absent from data). */
export function schemaFieldType(label: string): string | null {
  return SCHEMA_BY_LABEL.get(label)?.type ?? null;
}

/** Option labels for a single-select radio field defined with an `options` array (e.g. 8.2, 4.4, 4.6). */
export function optionsForLabel(label: string): string[] | null {
  const opts = SCHEMA_BY_LABEL.get(label)?.options;
  if (opts && opts.length > 0) return opts.map(o => o.label);
  return null;
}
