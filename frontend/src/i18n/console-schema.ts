/**
 * Console dictionary contract.
 *
 * Kept separate from `MessageSchema` so the console's vocabulary can grow
 * phase by phase without turning the landing-page dictionary into a thousand
 * line file. Both locales are typed against this, so a key added here and
 * forgotten in a translation is a compile error rather than a raw key
 * rendered in the UI.
 *
 * Naming: keys describe *intent* (`nav.testRuns`), never phrasing. Anything
 * that reads differently depending on the numbers involved takes `{params}`
 * and is interpolated by `t()`.
 */
export interface ConsoleMessageSchema {
  readonly nav: {
    readonly dashboard: string
    readonly projects: string
    readonly overview: string
    readonly apiClient: string
    /**
     * Second line under the label, for the two entries in 测试方式 / Testing
     * that would otherwise read as the same destination: one drives a request
     * by hand, the other has the agent read a specification. Neither is a
     * precondition of the other.
     */
    readonly apiClientHint: string
    readonly aiTestLab: string
    readonly aiTestLabHint: string
    readonly testPlans: string
    readonly workflows: string
    readonly testRuns: string
    readonly reports: string
    readonly settings: string

    readonly sectionWorkspace: string
    readonly sectionTesting: string
    readonly sectionDesign: string
    readonly sectionExecution: string

    readonly notBuiltYet: string
    readonly collapse: string
    readonly expand: string
    readonly openMenu: string
    readonly closeMenu: string
  }

  readonly project: {
    readonly switcherLabel: string
    readonly noProjects: string
    /** `Updated {time}` — `{time}` is a localized relative timestamp. */
    readonly updated: string
    readonly notFound: string
    readonly notFoundBody: string
    readonly backToProjects: string
    /** The action that creates a project the user names themselves. */
    readonly create: string
    readonly createTitle: string
    readonly createBody: string
    readonly nameLabel: string
    readonly namePlaceholder: string
    readonly baseUrlLabel: string
    readonly baseUrlPlaceholder: string
    readonly baseUrlHint: string
    readonly createConfirm: string
    readonly createFailed: string
  }

  readonly environment: {
    readonly label: string
    readonly development: string
    readonly staging: string
    readonly production: string
    readonly baseUrl: string
    readonly variables: string
    readonly empty: string
    readonly secret: string
  }

  readonly topbar: {
    readonly notifications: string
    readonly notificationsEmpty: string
    readonly markAllRead: string
    readonly clear: string
    readonly profile: string
    readonly settings: string
    readonly logout: string
    readonly signIn: string
    readonly guest: string
    readonly account: string
    readonly toggleSidebar: string
  }

  readonly auth: {
    readonly title: string
    readonly body: string
    readonly continueWith: string
    readonly github: string
    readonly google: string
    readonly demoNote: string
    readonly cancel: string
  }

  readonly dashboard: {
    readonly title: string
    readonly subtitle: string
    readonly agentTitle: string
    readonly agentBody: string
    readonly projectsTitle: string
    readonly openProject: string
    readonly plansTitle: string
    readonly plansEmpty: string
    readonly runsTitle: string
    readonly runsEmpty: string
    readonly viewAll: string
  }

  readonly overview: {
    readonly title: string
    readonly about: string
    readonly noDescription: string
    readonly environments: string
    readonly spec: string
    readonly noSpec: string
    readonly updated: string
    readonly quickStart: string
    readonly quickStartBody: string
    readonly openApiClient: string
    readonly openTestLab: string
  }

  readonly apiClient: {
    readonly title: string
    readonly subtitle: string
    readonly newRequest: string
    readonly request: string
    readonly response: string
    readonly send: string
    readonly sending: string
    readonly cancelRequest: string
    readonly save: string
    readonly saveTitle: string
    readonly saveName: string
    readonly saveNamePlaceholder: string
    readonly saveCollection: string
    readonly saveCollectionPlaceholder: string
    readonly saveConfirm: string
    readonly saved: string
    /** `Editing {name}` — shown when a saved request is open. */
    readonly editing: string

    readonly urlPlaceholder: string
    readonly baseUrlHint: string
    /** `Path params` / request body hints under an empty editor. */
    readonly paramsHint: string
    readonly headersHint: string

    readonly tabs: {
      readonly params: string
      readonly headers: string
      readonly auth: string
      readonly body: string
      readonly responseBody: string
      readonly responseHeaders: string
      readonly cookies: string
    }

    readonly keyValue: {
      readonly enabled: string
      readonly key: string
      readonly value: string
      readonly description: string
      readonly delete: string
      readonly add: string
      readonly keyPlaceholder: string
      readonly valuePlaceholder: string
      readonly descriptionPlaceholder: string
      readonly empty: string
    }

    readonly auth: {
      readonly type: string
      readonly none: string
      readonly noneHint: string
      readonly bearer: string
      readonly bearerToken: string
      readonly bearerPlaceholder: string
      readonly basic: string
      readonly username: string
      readonly password: string
      readonly apiKey: string
      readonly apiKeyName: string
      readonly apiKeyValue: string
      readonly apiKeyIn: string
      readonly inHeader: string
      readonly inQuery: string
      readonly preview: string
      readonly previewEmpty: string
    }

    readonly body: {
      readonly mode: string
      readonly none: string
      readonly noneHint: string
      readonly json: string
      readonly raw: string
      readonly jsonPlaceholder: string
      readonly rawPlaceholder: string
      readonly format: string
      readonly formatFailed: string
      /** `Invalid JSON at line {line}` */
      readonly invalidAtLine: string
      readonly invalid: string
    }

    readonly json: {
      readonly tree: string
      readonly raw: string
      readonly expandAll: string
      readonly collapseAll: string
      readonly copy: string
      /** `{count} items` / `{count} keys` for a collapsed container. */
      readonly arrayItems: string
      readonly objectKeys: string
      readonly empty: string
    }

    /** Strings for the response pane; `response` above is its title. */
    readonly responsePanel: {
      readonly waiting: string
      readonly waitingHint: string
      readonly noHeaders: string
      readonly noCookies: string
      readonly status: string
      readonly time: string
      readonly size: string
      readonly receivedAt: string
    }

    readonly collections: {
      readonly title: string
      readonly empty: string
      readonly emptyHint: string
      readonly delete: string
      /** `Delete "{name}"?` */
      readonly deleteConfirm: string
      readonly expand: string
      readonly collapse: string
    }

    readonly history: {
      readonly title: string
      readonly empty: string
      readonly emptyHint: string
      readonly clear: string
      readonly clearConfirm: string
    }

    readonly variables: {
      readonly title: string
      readonly hint: string
      readonly empty: string
      readonly masked: string
      readonly copy: string
    }

    readonly error: {
      readonly title: string
      readonly unresolvedVariables: string
      readonly missingBaseUrl: string
      readonly network: string
      /** The proxy stopped waiting for the target. */
      readonly timeout: string
      /** The proxy could not open a connection to the target. */
      readonly unreachable: string
      /** The address was refused by the proxy's own policy. */
      readonly blocked: string
      /** The URL is not one the proxy will send. */
      readonly invalid: string
      /** The target's answer was larger than the proxy will buffer. */
      readonly tooLarge: string
      /** No valid guest session, so the platform refused the call. */
      readonly unauthorized: string
      readonly projectNotReady: string
      readonly dismiss: string
    }

    readonly agent: {
      readonly generate: string
      readonly generateHint: string
      readonly queued: string
    }
  }

  readonly aiTest: {
    readonly title: string
    readonly subtitle: string

    /** Pipeline step labels, in order. */
    readonly pipeline: {
      readonly spec: string
      readonly analyze: string
      readonly understanding: string
      readonly plan: string
      readonly approve: string
      readonly execute: string
    }

    readonly upload: {
      readonly heading: string
      readonly dropTitle: string
      readonly dropHint: string
      readonly selectFile: string
      readonly useDemo: string
      readonly divider: string
      readonly pasteTitle: string
      readonly pastePlaceholder: string
      readonly pasteAction: string
      readonly supported: string
    }

    /** Specification syntax names. Proper nouns, identical in both locales. */
    readonly format: {
      readonly openapi3: string
      readonly swagger2: string
    }

    readonly spec: {
      readonly title: string
      readonly version: string
      readonly format: string
      readonly source: string
      readonly filename: string
      readonly endpoints: string
      readonly loadedAt: string
      readonly reanalyze: string
      readonly replace: string
      readonly analyze: string

      readonly sourceDemo: string
      readonly sourceUpload: string
      readonly sourcePaste: string
      readonly sourceHandoff: string
    }

    /** Progress checklist shown while the agent works. */
    readonly stages: {
      readonly parsing: string
      readonly endpoints: string
      readonly authentication: string
      readonly dependencies: string
      readonly risks: string
    }

    readonly analyzing: {
      readonly title: string
      readonly subtitle: string
    }

    readonly errors: {
      readonly title: string
      readonly parseFailed: string
      readonly unsupportedFormat: string
      readonly noEndpoints: string
      readonly analyzeFailed: string
      readonly generateFailed: string
      /** 409: a plan for this document is already stored. */
      readonly planExists: string
      /** 404: the task id names no task. */
      readonly taskNotFound: string
      /** The task could not be read at all: transport, or a body we cannot draw. */
      readonly loadFailed: string
      /** No project was ready, so the operation was refused before any request. */
      readonly projectNotReady: string
      readonly dismiss: string
    }

    /**
     * The sentence the console sends as `agent_tasks.prompt`.
     *
     * The backend stores it verbatim and the deterministic pipeline does not
     * read it yet, but the column is NOT NULL and the value is the user's
     * request in their own language -- which is what a model would be given
     * when the pipeline starts calling one.
     */
    readonly task: {
      readonly prompt: string
    }

    readonly understanding: {
      readonly title: string
      readonly subtitle: string
      readonly resources: string
      readonly endpoints: string
      readonly authentication: string
      readonly dependencies: string
      readonly risks: string
      readonly noAuthentication: string
      readonly scheme: string
      readonly tokenSource: string
      readonly tokenField: string
      readonly protectedEndpoints: string
      readonly none: string
      readonly requiresAuth: string
    }

    readonly dependencies: {
      readonly rationaleToken: string
      readonly rationaleIdentity: string
      readonly rationaleReference: string
      readonly rationaleLifecycle: string
      readonly rationaleSubResource: string
      readonly empty: string
    }

    readonly risks: {
      readonly empty: string
      readonly authTitle: string
      readonly authDetail: string
      readonly authorizationTitle: string
      readonly authorizationDetail: string
      readonly referenceTitle: string
      readonly referenceDetail: string
      readonly parentTitle: string
      readonly parentDetail: string
      readonly negativeTitle: string
      readonly negativeDetail: string
      readonly idempotencyTitle: string
      readonly idempotencyDetail: string
      readonly levelLow: string
      readonly levelMedium: string
      readonly levelHigh: string
      readonly categoryAuthentication: string
      readonly categoryDependency: string
      readonly categoryValidation: string
      readonly categoryNegativeCoverage: string
      readonly categoryIdempotency: string
      readonly categoryAuthorization: string
    }

    readonly findings: {
      readonly title: string
      readonly empty: string
      readonly parsed: string
      readonly parsedDecision: string
      readonly endpoints: string
      readonly endpointsDecision: string
      readonly authentication: string
      readonly authenticationDecision: string
      readonly dependencies: string
      readonly dependenciesDecision: string
      readonly risks: string
      readonly risksDecision: string
    }

    readonly evidence: {
      readonly format: string
      readonly endpoints: string
      readonly resources: string
      readonly protectedEndpoints: string
      readonly tokenSource: string
      readonly dependencies: string
      readonly risks: string
    }

    readonly plan: {
      readonly generate: string
      readonly generating: string
      readonly title: string
      readonly generatedBy: string
      readonly goal: string
      readonly risk: string
      readonly status: string
      readonly scenarios: string
      readonly steps: string
      readonly assertions: string
      readonly expected: string
      readonly empty: string
      readonly openDetail: string
      readonly run: string
      readonly runBlocked: string
      readonly edit: string
      readonly editTitle: string
      readonly nameLabel: string
      readonly save: string
      /** `{resource} Lifecycle Validation` */
      readonly lifecycleName: string
      /** `Validate the complete {resource} lifecycle...` */
      readonly lifecycleGoal: string
      readonly sourceGenerated: string
      readonly sourceHandoff: string
      readonly executionNextPhase: string
      readonly regenerate: string
      readonly regenerateTitle: string
      readonly regenerateBody: string
      readonly regenerateConfirm: string
      readonly regenerateCancel: string
      readonly regenerateSuccess: string
    }

    readonly status: {
      readonly draft: string
      readonly in_review: string
      readonly approved: string
      readonly rejected: string
    }

    readonly scenario: {
      readonly authenticationName: string
      readonly authenticationDescription: string
      readonly authenticationExpected: string
      readonly lifecycleName: string
      readonly lifecycleDescription: string
      readonly lifecycleExpected: string
      readonly paymentName: string
      readonly paymentDescription: string
      readonly paymentExpected: string
      readonly negativeName: string
      readonly negativeDescription: string
      readonly negativeExpected: string
      /** Used when the document is too thin for any other rule to fire. */
      readonly smokeName: string
      readonly smokeDescription: string
      readonly smokeExpected: string
    }

    readonly step: {
      readonly request: string
      readonly extract: string
      readonly assert: string
      readonly login: string
      readonly fetchIdentity: string
      readonly createResource: string
      readonly readResource: string
      readonly subResourceAction: string
      /** `Extract {variable} from the response` */
      readonly extractVariable: string
      readonly extractVariableFrom: string
      readonly callEndpoint: string
      readonly assertResponse: string
      readonly assertRequestResponse: string
      readonly invalidBody: string
      readonly boundaryValue: string
      readonly unauthenticated: string
    }

    readonly assertion: {
      readonly statusIs: string
      readonly fieldPresent: string
      readonly fieldIs: string
      readonly headerIs: string
      readonly resourceCreated: string
    }

    readonly approval: {
      readonly approve: string
      readonly approveTitle: string
      readonly approveBody: string
      /** `{scenarios} scenarios · {requests} requests · Risk {risk}` */
      readonly approveSummary: string
      readonly approveConfirm: string
      readonly cancel: string
      readonly reject: string
      readonly rejectTitle: string
      readonly rejectBody: string
      readonly rejectReason: string
      readonly rejectReasonPlaceholder: string
      readonly rejectConfirm: string
      readonly reasonRequired: string
      readonly approved: string
      readonly rejected: string
    }

    readonly handoff: {
      readonly title: string
      readonly source: string
      readonly fromApiClient: string
      readonly analyze: string
      readonly useDemo: string
      readonly dismiss: string
      readonly description: string
      /** Name given to the one-endpoint specification built from a handoff. */
      readonly specTitle: string
    }
  }

  readonly plans: {
    readonly title: string
    readonly subtitle: string
    readonly openLab: string
    readonly empty: string
    readonly emptyHint: string
    readonly generatedAt: string
    readonly approvedAt: string
    readonly source: string
    readonly backToList: string
    readonly viewAll: string
    readonly notFound: string
    readonly notFoundBody: string
    readonly version: string
    readonly current: string
    readonly runs: string
    readonly retry: string
  }

  /**
   * Test runs.
   *
   * `status` and `stepStatus` are separate on purpose: a run and a step fail
   * in different ways, and one shared set of words would have to be vague
   * enough to cover both.
   */
  readonly runs: {
    readonly title: string
    readonly subtitle: string

    readonly newRun: string
    readonly creating: string
    readonly openLab: string
    readonly empty: string
    readonly emptyHint: string
    /** Explains why Run is unavailable — stated, never merely implied. */
    readonly blocked: string

    readonly plan: string
    readonly planId: string
    readonly environment: string
    readonly baseUrl: string
    readonly variables: string
    readonly variablesHint: string
    readonly runtimeVariables: string
    readonly noRuntimeVariables: string
    readonly runtimeVariablesHint: string
    readonly createdAt: string
    readonly finishedAt: string
    readonly duration: string
    readonly live: string
    /** The run is still going; the stream is open. */
    readonly following: string

    readonly cancel: string
    readonly cancelling: string
    readonly cancelConfirm: string

    readonly expected: string
    readonly actual: string
    readonly noSteps: string
    readonly noRunsYet: string

    readonly backToList: string
    readonly notFound: string
    readonly notFoundBody: string
    readonly openPlan: string

    readonly status: {
      readonly queued: string
      readonly running: string
      readonly passed: string
      readonly failed: string
      readonly cancelled: string
    }

    readonly stepStatus: {
      readonly pending: string
      readonly running: string
      readonly passed: string
      readonly failed: string
      readonly skipped: string
    }

    readonly errors: {
      readonly title: string
      readonly notFound: string
      /** The run's plan `{plan}` has to be approved before it can run. */
      readonly unauthorized: string
    readonly notApproved: string
      readonly noPlan: string
      readonly createFailed: string
      readonly loadFailed: string
      readonly cancelFailed: string
      readonly dismiss: string
    }

    /**
     * What a step left behind.
     *
     * `endpoint`, `extracted` and `checked` are emitted as data by the run
     * service rather than written as `t('…')` literals, so they carry the
     * dictionary path the engine actually uses.
     */
    readonly evidence: {
      readonly heading: string
      readonly endpoint: string
      readonly extracted: string
      readonly checked: string
    }

    /** Why a step could not run. Emitted as data, like the evidence labels. */
    readonly failure: {
      readonly heading: string
      /** A request step that names no endpoint cannot be executed. */
      readonly notExecutable: string
    }
  }

  /** C33: the printable report of one already-finished run. */
  readonly report: {
    readonly open: string
    readonly title: string
    readonly subtitle: string
    readonly generatedAt: string
    readonly runId: string
    readonly project: string
    readonly plan: string
    readonly planId: string
    readonly environment: string
    readonly baseUrl: string
    readonly status: string
    readonly summary: string
    readonly createdAt: string
    readonly startedAt: string
    readonly finishedAt: string
    readonly duration: string

    readonly scenarios: string
    readonly steps: string
    readonly assertions: string
    readonly passed: string
    readonly failed: string
    readonly skipped: string
    readonly passedSteps: string
    readonly failedSteps: string
    readonly skippedSteps: string
    readonly passedAssertions: string
    readonly failedAssertions: string
    readonly skippedAssertions: string

    readonly execution: string
    readonly scenario: string
    readonly assertion: string
    readonly type: string
    readonly description: string
    readonly http: string
    readonly target: string
    readonly expected: string
    readonly actual: string
    readonly evidence: string
    readonly error: string

    readonly conclusion: string
    readonly conclusionPassed: string
    readonly conclusionFailed: string
    readonly conclusionCancelled: string

    readonly limitations: string
    readonly limitationsBody: string
    readonly noScenarios: string
    readonly noAssertions: string
    readonly noEvidence: string
    readonly noActual: string

    readonly print: string
    readonly printHint: string
    readonly pageNumbersHint: string
    readonly back: string
    readonly unavailable: string
    readonly unavailableBody: string
    readonly notFound: string
    readonly notFoundBody: string
    readonly generatedFromRun: string
    readonly centerTitle: string
    readonly centerSubtitle: string
    readonly noReports: string
    readonly noReportsHint: string
    readonly openReport: string
    readonly download: string
    readonly saved: string
    readonly savedHint: string
    readonly openSaved: string
    readonly generating: string
    readonly generateAndSave: string
    readonly loadFailed: string
    readonly generateFailed: string
    readonly notReady: string
    readonly downloadFailed: string
    readonly reportName: string
    readonly runStatus: string
  }

  readonly common: {
    readonly loading: string
    readonly cancel: string
    readonly confirm: string
    readonly close: string
    readonly none: string
    readonly unknown: string
    readonly copy: string
    readonly copied: string
    readonly copyFailed: string
    readonly delete: string
    readonly save: string
    readonly add: string
  }
}
