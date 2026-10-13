/** Roles allowed per API operation, mirrored from contracts/v1/routes.json so the console can hide actions a
 * user cannot take. The backend enforces every role again; a test keeps this map equal to the contract. */
export const OPERATION_ROLES = {
  logout: ["admin", "researcher", "moderator", "publisher", "analyst"],
  getMe: ["admin", "researcher", "moderator", "publisher", "analyst"],
  importProjects: ["researcher", "admin"],
  createProject: ["researcher", "admin"],
  listProjects: ["admin", "researcher", "moderator", "publisher", "analyst"],
  getProject: ["admin", "researcher", "moderator", "publisher", "analyst"],
  updateProjectConfig: ["researcher"],
  startRun: ["researcher"],
  listRuns: ["admin", "researcher", "moderator", "publisher", "analyst"],
  getRun: ["admin", "researcher", "moderator", "publisher", "analyst"],
  streamRunEvents: ["admin", "researcher", "moderator", "publisher", "analyst"],
  cancelRun: ["researcher"],
  listSources: ["admin", "researcher", "moderator", "publisher", "analyst"],
  getSourceRevision: ["admin", "researcher", "moderator", "publisher", "analyst"],
  listMedia: ["admin", "researcher", "moderator", "publisher", "analyst"],
  withdrawSource: ["moderator", "admin"],
  decideSourceLink: ["moderator"],
  listAliasProposals: ["admin", "researcher", "moderator", "publisher", "analyst"],
  decideAliasProposal: ["researcher", "moderator"],
  listFindings: ["admin", "researcher", "moderator", "publisher", "analyst"],
  reviseFinding: ["moderator"],
  decideFinding: ["moderator"],
  listReviewExcerpts: ["admin", "researcher", "moderator", "publisher", "analyst"],
  reviseReviewExcerpt: ["moderator"],
  decideReviewExcerpt: ["moderator"],
  createContentRevision: ["moderator"],
  listContentRevisions: ["moderator", "publisher"],
  getContentRevision: ["moderator", "publisher"],
  approveContentRevision: ["moderator"],
  decideContentRevision: ["moderator"],
  getPublicationState: ["admin", "researcher", "moderator", "publisher", "analyst"],
  publish: ["publisher"],
  getPublication: ["publisher"],
  rollbackPublication: ["publisher"],
  unpublishProject: ["publisher"],
  listCorrections: ["moderator"],
  decideCorrection: ["moderator"],
  getConnectorHealth: ["researcher", "admin"],
  listJobs: ["researcher", "admin"],
  getOpsSummary: ["admin", "researcher", "moderator", "publisher", "analyst"],
  listEvaluations: ["admin", "researcher", "moderator", "publisher", "analyst"],
  listUsers: ["admin"],
  createUser: ["admin"],
  updateUser: ["admin"],
  listSourcePolicies: ["admin", "researcher"],
  createSourcePolicyVersion: ["admin"],
  listAuditEvents: ["admin"],
} as const satisfies Record<string, readonly string[]>;

export type OperationId = keyof typeof OPERATION_ROLES;

export function can(roles: readonly string[] | undefined, operation: OperationId): boolean {
  const allowed: readonly string[] = OPERATION_ROLES[operation];
  return (roles ?? []).some((role) => allowed.includes(role));
}
