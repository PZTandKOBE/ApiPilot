import type { ConsoleMessageSchema } from '@/i18n/console-schema'

/** Source locale for the console. Every other locale is typed against it. */
export const consoleEnUS = {
  nav: {
    dashboard: 'Dashboard',
    projects: 'Projects',
    overview: 'Overview',
    apiClient: 'API Client',
    apiClientHint: 'Send requests by hand',
    aiTestLab: 'AI Test Lab',
    aiTestLabHint: 'The agent analyses your spec',
    testPlans: 'Test Plans',
    workflows: 'Workflows',
    testRuns: 'Test Runs',
    reports: 'Reports',
    settings: 'Settings',

    sectionWorkspace: 'Workspace',
    sectionTesting: 'Testing',
    sectionDesign: 'Test Design',
    sectionExecution: 'Execution',

    notBuiltYet: 'Coming in a later phase',
    collapse: 'Collapse sidebar',
    expand: 'Expand sidebar',
    openMenu: 'Open navigation',
    closeMenu: 'Close navigation',
  },
  project: {
    switcherLabel: 'Project',
    noProjects: 'No projects yet',
    updated: 'Updated {time}',
    notFound: 'Project not found',
    notFoundBody:
      'This project either does not exist or is not available to the current account.',
    backToProjects: 'Back to projects',
    create: 'New project',
    createTitle: 'New project',
    createBody: 'Give it a name. You can point it at an API now or later.',
    nameLabel: 'Project name',
    namePlaceholder: 'Checkout API',
    baseUrlLabel: 'Base URL',
    baseUrlPlaceholder: 'https://api.example.com',
    baseUrlHint: 'Optional. The environment a run sends its requests to.',
    createConfirm: 'Create project',
    createFailed: 'The project could not be created.',
  },
  environment: {
    label: 'Environment',
    development: 'Development',
    staging: 'Staging',
    production: 'Production',
    baseUrl: 'Base URL',
    variables: 'Variables',
    empty: 'No environments configured',
    secret: 'Secret',
  },
  topbar: {
    notifications: 'Notifications',
    notificationsEmpty: 'Nothing to catch up on',
    markAllRead: 'Mark all as read',
    clear: 'Clear all',
    profile: 'Profile',
    settings: 'Settings',
    logout: 'Log out',
    signIn: 'Sign in',
    guest: 'Guest',
    account: 'Account',
    toggleSidebar: 'Toggle sidebar',
  },
  auth: {
    title: 'Sign in',
    body: 'Signing in unlocks saved projects, test plans and shared reports. The API Client and the test lab stay usable as a guest.',
    continueWith: 'Continue with {provider}',
    github: 'GitHub',
    google: 'Google',
    demoNote: 'No auth server is connected yet — this signs in a demo account.',
    cancel: 'Not now',
  },
  dashboard: {
    title: 'Dashboard',
    subtitle: 'Everything the agent is working on, across your projects.',
    agentTitle: 'Agent activity',
    agentBody:
      'No analysis has run yet. Open AI Test Lab in a project to upload an OpenAPI document and let the agent build a test plan.',
    projectsTitle: 'Projects',
    openProject: 'Open project',
    plansTitle: 'Test plans awaiting approval',
    plansEmpty: 'No test plans yet',
    runsTitle: 'Recent test runs',
    runsEmpty: 'No test runs yet',
    viewAll: 'View all',
  },
  overview: {
    title: 'Overview',
    about: 'About',
    noDescription: 'This project has no description yet.',
    environments: 'Environments',
    spec: 'API specification',
    noSpec: 'No OpenAPI document uploaded',
    updated: 'Last updated',
    quickStart: 'Quick start',
    quickStartBody:
      'Compose a request by hand in the API Client, or let the agent read your specification and propose a test plan first.',
    openApiClient: 'Open API Client',
    openTestLab: 'Open AI Test Lab',
  },
  apiClient: {
    title: 'API Client',
    subtitle:
      'Compose a request by hand, send it, and inspect exactly what came back.',
    newRequest: 'New request',
    request: 'Request',
    response: 'Response',
    send: 'SEND',
    sending: 'Sending',
    cancelRequest: 'Cancel',
    save: 'Save',
    saveTitle: 'Save request',
    saveName: 'Request name',
    saveNamePlaceholder: 'Create order',
    saveCollection: 'Collection',
    saveCollectionPlaceholder: 'Orders',
    saveConfirm: 'Save',
    saved: 'Request saved',
    editing: 'Editing {name}',

    urlPlaceholder: 'https://api.example.com/orders or /orders',
    baseUrlHint: 'Relative paths resolve against the environment base URL.',
    paramsHint: 'Query parameters are appended to the URL in the order shown.',
    headersHint: 'Headers are sent as listed; blanks are ignored.',

    tabs: {
      params: 'Params',
      headers: 'Headers',
      auth: 'Auth',
      body: 'Body',
      responseBody: 'Body',
      responseHeaders: 'Headers',
      cookies: 'Cookies',
    },

    keyValue: {
      enabled: 'Enabled',
      key: 'Key',
      value: 'Value',
      description: 'Description',
      delete: 'Delete row',
      add: 'Add row',
      keyPlaceholder: 'key',
      valuePlaceholder: 'value',
      descriptionPlaceholder: 'optional note',
      empty: 'No entries yet — type in the row below to add one.',
    },

    auth: {
      type: 'Type',
      none: 'No auth',
      noneHint: 'This request is sent without credentials.',
      bearer: 'Bearer token',
      bearerToken: 'Token',
      bearerPlaceholder: '{{token}}',
      basic: 'Basic auth',
      username: 'Username',
      password: 'Password',
      apiKey: 'API key',
      apiKeyName: 'Key',
      apiKeyValue: 'Value',
      apiKeyIn: 'Add to',
      inHeader: 'Header',
      inQuery: 'Query params',
      preview: 'Sent as',
      previewEmpty: 'Nothing will be added to this request.',
    },

    body: {
      mode: 'Body type',
      none: 'None',
      noneHint: 'This request has no body.',
      json: 'JSON',
      raw: 'Raw',
      jsonPlaceholder: '{\n  "product_id": "prod_001",\n  "quantity": 2\n}',
      rawPlaceholder: 'Raw request body',
      format: 'Format',
      formatFailed: 'Cannot format invalid JSON',
      invalidAtLine: 'Invalid JSON at line {line}',
      invalid: 'Invalid JSON',
    },

    json: {
      tree: 'Tree',
      raw: 'Raw',
      expandAll: 'Expand all',
      collapseAll: 'Collapse all',
      copy: 'Copy',
      arrayItems: '{count} items',
      objectKeys: '{count} keys',
      empty: 'Empty response body',
    },

    responsePanel: {
      waiting: 'No response yet',
      waitingHint:
        'Send the request to see the status, timing and body here.',
      noHeaders: 'No response headers',
      noCookies: 'No cookies were set by this response',
      status: 'Status',
      time: 'Time',
      size: 'Size',
      receivedAt: 'Received',
    },

    collections: {
      title: 'Collections',
      empty: 'No saved requests yet',
      emptyHint: 'Send something, then use Save to keep it here.',
      delete: 'Delete request',
      deleteConfirm: 'Delete "{name}"? This cannot be undone.',
      expand: 'Expand',
      collapse: 'Collapse',
    },

    history: {
      title: 'History',
      empty: 'Nothing sent yet',
      emptyHint: 'Requests you send appear here, newest first.',
      clear: 'Clear history',
      clearConfirm: 'Clear the history for this project?',
    },

    variables: {
      title: 'Environment variables',
      hint: 'Reference these anywhere in the request as {{name}}.',
      empty: 'This environment defines no variables.',
      masked: 'Hidden',
      copy: 'Copy value',
    },

    error: {
      title: 'Request not sent',
      unresolvedVariables:
        'Variable {names} is not defined in the current environment.',
      missingBaseUrl:
        'A relative URL needs a base URL — configure one on the environment.',
      network: 'The request could not reach the transport.',
      timeout: 'The proxy gave up waiting for the target API.',
      unreachable: 'The proxy could not connect to the target API.',
      blocked:
        'The proxy refused this address. Only public addresses are called, so loopback, private and metadata targets never reach the network.',
      invalid: 'The target URL is not one the proxy can send.',
      tooLarge: 'The target answered with more than the proxy will buffer.',
      unauthorized:
        'This console has no valid guest session, so the request was not sent. Reload the page to get a new one.',
      projectNotReady:
        'No project is ready yet, so nothing was sent. Create or reload a project, then try again.',
      dismiss: 'Dismiss',
    },

    agent: {
      generate: 'Generate test',
      generateHint: 'Hand this request to the agent in the AI Test Lab',
      queued: 'Request handed to the agent — the AI Test Lab arrives next phase',
    },
  },
  aiTest: {
    title: 'AI Test Lab',
    subtitle:
      'Let the agent read your API, trace how its endpoints depend on each other, and propose a test plan.',

    pipeline: {
      spec: 'API Spec',
      analyze: 'Analyze',
      understanding: 'Understanding',
      plan: 'Test Plan',
      approve: 'Approve',
      execute: 'Execute',
    },

    upload: {
      heading: 'Upload an API specification',
      dropTitle: 'Drop an OpenAPI or Swagger file',
      dropHint: 'JSON or YAML · OpenAPI 3.x and Swagger 2.x',
      selectFile: 'Select file',
      useDemo: 'Use demo API',
      divider: 'or paste a document',
      pasteTitle: 'Paste specification',
      pastePlaceholder: 'Paste an OpenAPI or Swagger document here…',
      pasteAction: 'Analyze pasted document',
      supported: 'OpenAPI 3.x · Swagger 2.x · JSON or YAML',
    },

    format: {
      openapi3: 'OpenAPI 3',
      swagger2: 'Swagger 2',
    },

    spec: {
      title: 'Specification',
      version: 'Version',
      format: 'Format',
      source: 'Source',
      filename: 'File',
      endpoints: 'Endpoints',
      loadedAt: 'Loaded',
      reanalyze: 'Re-analyze',
      replace: 'Replace',
      analyze: 'Analyze API',

      sourceDemo: 'Demo API',
      sourceUpload: 'Uploaded file',
      sourcePaste: 'Pasted document',
      sourceHandoff: 'API Client request',
    },

    stages: {
      parsing: 'Parsing the document',
      endpoints: 'Discovering endpoints and resources',
      authentication: 'Detecting authentication',
      dependencies: 'Tracing the dependency path',
      risks: 'Identifying coverage risks',
    },

    analyzing: {
      title: 'Analyzing the API',
      subtitle: 'The agent is reading the specification. This does not run any requests.',
    },

    errors: {
      title: 'The agent could not finish',
      parseFailed: 'The document could not be parsed: {detail}',
      unsupportedFormat:
        'This does not look like an OpenAPI 3.x or Swagger 2.x document. Expected an "openapi" or "swagger" field at the top level.',
      noEndpoints:
        'The document parsed correctly but declares no endpoints under "paths", so there is nothing to test.',
      analyzeFailed: 'Analysis failed before it produced a result.',
      generateFailed: 'The test plan could not be generated from this analysis.',
      planExists:
        'A test plan for this document already exists. Regenerating one is not supported yet.',
      taskNotFound: 'No agent task with that id was found.',
      loadFailed: 'The agent task could not be loaded.',
      projectNotReady:
        'No project is ready yet, so nothing was sent. Create or reload a project, then try again.',
        dismiss: 'Dismiss',
    },

    task: {
      prompt: 'Design a test plan for {title}.',
    },

    understanding: {
      title: 'API Understanding',
      subtitle: 'What the agent read out of the specification.',
      resources: 'Resources',
      endpoints: 'Endpoints',
        authentication: 'Authentication',
      dependencies: 'Dependencies',
      risks: 'Potential risks',
      noAuthentication: 'This API declares no authentication scheme.',
      scheme: 'Scheme',
      tokenSource: 'Token source',
      tokenField: 'Token field',
      protectedEndpoints: 'Protected endpoints',
      none: 'None',
      requiresAuth: 'Requires authentication',
    },

    dependencies: {
        rationaleToken: '{to} cannot be called without the token issued by {from}.',
      rationaleIdentity:
        '{to} acts on behalf of the identity returned by {from}, so that call has to run first.',
      rationaleReference: '{to} references the {binding} owned by {from}.',
      rationaleLifecycle: '{to} needs the {binding} returned when {from} created it.',
      rationaleSubResource:
        '{to} operates on a resource that has to exist before the call is meaningful.',
      empty: 'No dependencies were found on the lifecycle path.',
    },

    risks: {
      empty: 'No coverage risks were identified.',
      authTitle: '{count} endpoints require authentication',
      authDetail:
        'Every protected endpoint has a path an unauthenticated caller should not be able to take. Nothing in the document states what that path returns.',
      authorizationTitle: '{count} endpoints read a resource belonging to an account',
      authorizationDetail:
        'Reading another account’s resource should be refused. Ownership checks are assumed but never documented.',
      referenceTitle: '{endpoint} depends on {binding}',
      referenceDetail:
        'The call is only valid when {binding} refers to a resource that already exists. An unknown value is worth covering.',
      parentTitle: '{endpoint} acts on an existing resource',
      parentDetail:
        'The action is only meaningful after the resource exists. Calling it with an unknown id is untested.',
      negativeTitle: '{field} is constrained but has no negative case',
      negativeDetail:
        'The document constrains {field} on {endpoint} without describing an invalid-input case. Boundary and type violations are the most common source of defects.',
      idempotencyTitle: '{count} DELETE endpoints have no idempotency coverage',
      idempotencyDetail:
        'Repeating a delete should be safe. Whether a second call returns 204 or 404 is not stated.',
      levelLow: 'Low',
      levelMedium: 'Medium',
      levelHigh: 'High',
      categoryAuthentication: 'Authentication',
      categoryDependency: 'Dependency',
      categoryValidation: 'Validation',
      categoryNegativeCoverage: 'Negative coverage',
      categoryIdempotency: 'Idempotency',
      categoryAuthorization: 'Authorization',
    },

    findings: {
      title: 'Agent activity',
      empty: 'The agent has not run yet.',
      parsed: 'Parsed the {format} document',
      parsedDecision: 'The document is a well-formed specification and can be analysed.',
      endpoints: 'Discovered {count} endpoints across {resources} resources',
      endpointsDecision: 'Endpoints are grouped by their tags, which is how the plan organises coverage.',
      authentication: 'Detected {scheme} authentication',
      authenticationDecision:
        'The credential is issued by {source}, so that call has to run before any protected endpoint.',
      dependencies: 'Traced {count} dependencies along the lifecycle path',
      dependenciesDecision: 'The plan executes them in dependency order rather than independently.',
      risks: 'Identified {count} coverage risks',
      risksDecision: 'Each risk becomes at least one scenario in the generated plan.',
    },

    evidence: {
      format: 'Format',
      endpoints: 'Endpoints',
      resources: 'Resources',
      protectedEndpoints: 'Protected',
      tokenSource: 'Token source',
      dependencies: 'Dependencies',
      risks: 'Risks',
    },

    plan: {
      generate: 'Generate test plan',
      generating: 'Generating…',
      title: 'Test plan',
      generatedBy: 'Generated by the agent',
      goal: 'Goal',
      risk: 'Risk',
      status: 'Status',
      scenarios: 'Scenarios',
      steps: 'Steps',
      assertions: 'Assertions',
      expected: 'Expected',
      empty: 'No test plan has been generated for this specification yet.',
      openDetail: 'Open full plan',
      run: 'Run test',
      runBlocked: 'This test plan has to be approved before it can run.',
      edit: 'Edit',
      editTitle: 'Edit test plan',
      nameLabel: 'Name',
        save: 'Save',
      lifecycleName: '{resource} lifecycle validation',
      lifecycleGoal:
        'Validate the complete {resource} lifecycle, from authentication through to the dependent action.',
      sourceGenerated: 'Generated',
      sourceHandoff: 'From API Client',
      executionNextPhase: 'Execution runs in the next phase. The plan is approved and ready.',
    },

    status: {
      draft: 'Draft',
      in_review: 'In review',
      approved: 'Approved',
      rejected: 'Rejected',
    },

    scenario: {
      authenticationName: 'User authentication',
      authenticationDescription:
        'Call the token source, then spend the token against a protected endpoint.',
      authenticationExpected:
        'Authentication succeeds and the token grants access to the identity endpoint.',
      lifecycleName: '{resource} creation and retrieval',
      lifecycleDescription: 'Create a resource, then read it back using the id it returned.',
      lifecycleExpected: '{resource} is created and can be retrieved by the returned id.',
      paymentName: 'Dependent action',
      paymentDescription: '{endpoint} runs against a resource created earlier in the plan.',
      paymentExpected: 'The action succeeds for a resource that already exists.',
      negativeName: 'Negative cases',
      negativeDescription: 'Send requests the API is expected to refuse.',
      negativeExpected: 'Each invalid request is refused with an error status.',
          smokeName: 'Endpoint responds as documented',
      smokeDescription:
        'Call {endpoint} and check the answer matches its contract. The document is too thin to derive anything more specific.',
      smokeExpected: '{endpoint} answers with its documented success status.',
    },

    step: {
      request: 'Request',
      extract: 'Extract',
      assert: 'Assert',
      login: 'Sign in and obtain a token',
      fetchIdentity: 'Read the authenticated identity',
        createResource: 'Create {resource}',
      readResource: 'Read {resource} back by id',
          subResourceAction: 'Perform the {action} action on the resource',
      extractVariable: 'Extract {variable} from the response',
      callEndpoint: 'Call {endpoint}',
      assertResponse: 'Assert the responses match expectations',
      invalidBody: 'Call {endpoint} without its required fields',
      boundaryValue: 'Call {endpoint} with a value outside the allowed range',
      unauthenticated: 'Call {endpoint} without credentials',
    },

    assertion: {
      statusIs: 'The response status is {status}',
      fieldPresent: 'The response body contains {field}',
      resourceCreated: 'The created resource is retrievable by its id',
    },

    approval: {
      approve: 'Approve & continue',
      approveTitle: 'Approve this test plan?',
      approveBody: 'You are about to approve this test plan.',
      approveSummary: '{scenarios} scenarios · {requests} requests · Risk {risk}',
      approveConfirm: 'Approve plan',
      cancel: 'Cancel',
      reject: 'Reject',
      rejectTitle: 'Reject this test plan',
      rejectBody: 'Tell the agent why this plan is not usable.',
      rejectReason: 'Reason',
      rejectReasonPlaceholder: 'What is missing or wrong?',
      rejectConfirm: 'Reject plan',
      reasonRequired: 'A reason is required to reject a plan.',
      approved: 'Test plan approved. It can now be executed.',
      rejected: 'Test plan rejected.',
    },

    handoff: {
      title: 'Request received from the API Client',
      source: 'Source',
      fromApiClient: 'API Client',
      analyze: 'Analyze this request',
      useDemo: 'Use demo API instead',
      dismiss: 'Dismiss',
      description:
        'This request came from the API Client. The agent can analyse it as a one-endpoint API.',
      specTitle: 'API Client request',
    },
  },
  plans: {
    title: 'Test Plans',
    subtitle: 'Review and manage test plans generated from API understanding.',
    openLab: 'Open AI Test Lab',
    empty: 'No test plans yet',
    emptyHint:
      'Open the AI Test Lab, point the agent at an API specification, and generate a plan from what it finds.',
    generatedAt: 'Generated',
    approvedAt: 'Approved',
    source: 'Source',
    backToList: 'Back to Test Plans',
    viewAll: 'View all plans',
    notFound: 'Test plan not found',
    notFoundBody:
      'This plan either does not exist or belongs to a different specification than the one loaded.',
  },
  runs: {
    title: 'Test Runs',
    subtitle:
      'Every run of an approved plan, with what each step actually did and what it left behind.',

    newRun: 'Start a run',
    creating: 'Starting…',
    openLab: 'Open AI Test Lab',
    empty: 'No test runs yet',
    emptyHint:
      'An approved plan is what a run is started from. Approve one and it can be run from here.',
    blocked: 'A run needs an approved plan for a loaded specification.',

    plan: 'Plan',
    environment: 'Environment',
    baseUrl: 'Base URL',
    variables: 'Variables',
    createdAt: 'Started',
    finishedAt: 'Finished',
    duration: 'Took',
    live: 'Live',
    following: 'Following this run as it happens.',

    cancel: 'Cancel run',
    cancelling: 'Cancelling…',
    cancelConfirm: 'Cancel this run? Steps that have not run yet will be skipped.',

    expected: 'Expected',
    actual: 'Actual',
    noSteps: 'This scenario has no steps.',
    noRunsYet: 'Nothing has run yet.',

    backToList: 'Back to Test Runs',
    notFound: 'Test run not found',
    notFoundBody:
      'This run either does not exist or was created against a different project.',
    openPlan: 'Open the plan',

    status: {
      queued: 'Queued',
      running: 'Running',
      passed: 'Passed',
      failed: 'Failed',
      cancelled: 'Cancelled',
    },

    stepStatus: {
      pending: 'Pending',
      running: 'Running',
      passed: 'Passed',
      failed: 'Failed',
      skipped: 'Skipped',
    },

    errors: {
      title: 'The run could not continue',
      unauthorized:
        'Your guest session has expired. A new one has been started — please try again.',
      notFound: 'No run with that id was found.',
      notApproved: '“{plan}” has to be approved before it can run.',
      noPlan: 'There is no approved plan to run yet.',
      createFailed: 'The run could not be created.',
      loadFailed: 'The run could not be loaded.',
      cancelFailed: 'The run could not be cancelled.',
      dismiss: 'Dismiss',
    },

    evidence: {
      heading: 'Evidence',
      endpoint: 'Requested',
      extracted: 'Extracted',
      checked: 'Checks',
    },

    failure: {
      heading: 'Failure',
      notExecutable: 'This step names no endpoint, so there is nothing to call.',
    },
  },

  common: {
    loading: 'Loading',
    cancel: 'Cancel',
    confirm: 'Confirm',
    close: 'Close',
    none: 'None',
    unknown: 'Unknown',
    copy: 'Copy',
    copied: 'Copied',
    copyFailed: 'Could not copy',
    delete: 'Delete',
    save: 'Save',
    add: 'Add',
  },
} satisfies ConsoleMessageSchema
