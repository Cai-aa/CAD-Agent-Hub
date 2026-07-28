# Workbench MCP adapter contract

## Capability discovery

Map the available MCP tools to logical actions before editing a project. Tool names are implementation-specific.

| Logical action | Required evidence |
|---|---|
| `PROBE_BRIDGE` | server version, transport health, round-trip response |
| `PROBE_SESSION` | active project, systems, Mechanical `Model`, analyses |
| `OPEN_OR_CREATE_PROJECT` | path and non-destructive disposition |
| `EXECUTE_WORKBENCH_SCRIPT` | script result and Workbench-side exception text |
| `EXECUTE_MECHANICAL_SCRIPT` | stdout/result payload and Mechanical-side exception text |
| `QUERY_TREE` | object names, types, states, scopes |
| `QUERY_GEOMETRY` | entity properties sufficient for semantic selection |
| `CREATE_NAMED_SELECTION` | name, scoped entities, validation properties |
| `CONFIGURE_ANALYSIS` | settings read back after assignment |
| `GENERATE_MESH` | success, nodes, elements, metric summary |
| `SOLVE` | solution state, solve log, converged time |
| `QUERY_RESULT` | scoped value, unit, time/mode/load step |
| `EXPORT_EVIDENCE` | existing file path and nonzero size |
| `SAVE_PROJECT` | final project/database path |

Do not confuse these states:

```text
bridge reachable -> Workbench context available -> Project available
-> Mechanical Model loaded -> analysis editable -> solution valid
```

Report the deepest proven state.

## Preferred adaptation order

1. Use purpose-built MCP tools when they return enough state for validation.
2. Use a generic Mechanical Python executor for operations not exposed atomically.
3. Use a Workbench journal executor for system creation, linking, or project-level work.
4. Stop as unsupported when neither the native tool nor safe scripting path exists.

For script execution, make operations idempotent by finding objects by semantic name before creating them. Read settings back and return a compact JSON payload. Do not rely on fixed DataModel IDs between sessions.

## Capability matrix

At minimum, record booleans for:

```json
{
  "project_open_save": true,
  "mechanical_model_query": true,
  "geometry_property_query": true,
  "named_selection": true,
  "materials": true,
  "connections": true,
  "mesh_controls": true,
  "mesh_metrics": true,
  "solve": true,
  "solver_output": true,
  "result_query": true,
  "artifact_export": true,
  "generic_mechanical_python": true
}
```

State the impact of every missing capability. For example, missing mesh metrics means the Skill may generate a mesh but cannot certify geometric quality.

## Script safety

- Refuse to import over a non-empty model unless authorized.
- Resolve objects by names and validated properties.
- Place generated scripts and outputs in the task workspace or user-approved case directory.
- Return exceptions verbatim with the phase and operation.
- Save only after successful gates or at explicit recovery checkpoints.
- Keep raw solver/result payloads even when a normalized report is generated.
