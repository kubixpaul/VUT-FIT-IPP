#!/usr/bin/env node
/**
 * An integration testing script for the SOL26 interpreter.
 *
 * IPP: You can implement the entire tool in this file if you wish, but it is recommended to split
 *      the code into multiple files and modules as you see fit.
 *
 *      Below, you have some code to get you started with the CLI argument parsing and logging setup,
 *      but you are **free to modify it** in whatever way you like.
 *
 * Author: Ondřej Ondryáš <iondryas@fit.vut.cz>
 *
 * AI usage notice: The author used OpenAI Codex to create the implementation of this
 *                  module based on its Python counterpart.
 */

import { existsSync, lstatSync, writeFileSync, readdirSync, readFileSync, mkdtempSync, rmSync } from "node:fs";
import { dirname, resolve, join, basename } from "node:path";
import { parseArgs } from "node:util";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";

import { TestReport, TestCaseDefinitionFile, TestCaseDefinition, UnexecutedReason, UnexecutedReasonCode, TestCaseType, TestCaseReport, CategoryReport, TestResult } from "./models.js";

import { pino } from "pino";

const logger = pino({
  transport: {
    target: "pino-pretty",
    options: {
      colorize: true,
      destination: 2,
    },
  },
});

interface CliArguments {
  tests_dir: string;
  recursive: boolean;
  output: string | null;
  dry_run: boolean;
  include: string[] | null;
  include_category: string[] | null;
  include_test: string[] | null;
  exclude: string[] | null;
  exclude_category: string[] | null;
  exclude_test: string[] | null;
  verbose: number;
  regex_filters: boolean;
}

function writeResult(resultReport: TestReport, outputFile: string | null): void {
  /**
   * Writes the final report to the specified output file or standard output if no file is provided.
   */
  const resultJson = JSON.stringify(resultReport, null, 2);
  if (outputFile !== null) {
    writeFileSync(outputFile, resultJson, "utf8");
    return;
  }

  console.log(resultJson);
}

const DOUBLE_LETTER_SHORT_OPTION_NORMALIZATION = new Map<string, string>([
  ["-ic", "--include-category"],
  ["-it", "--include-test"],
  ["-ec", "--exclude-category"],
  ["-et", "--exclude-test"],
]);

const HELP_TEXT = [
  "Usage:",
  "  tester [options] tests_dir",
  "",
  "Positional arguments:",
  "  tests_dir                 Path to a directory with the test cases in the SOLtest format.",
  "",
  "Options:",
  "  -h, --help                Show this help message and exit.",
  "  -r, --recursive           Recursively search for test cases in subdirectories of the provided directory.",
  "  -o, --output <path>       The output file to write the test results to. If not provided, results will be printed to standard output.",
  "  --dry-run                 Perform a dry run: discover the test cases but don't actually execute them.",
  "  -i, --include <value>     Include only test cases with the specified name or category. Can be used multiple times to specify multiple criteria.Can be combined with -ic and -it.",
  "  -ic, --include-category <value>",
  "                            Include only test cases with the specified category. Can be used multiple times to specify multiple accepted categories. Can be combined with -it and -i.",
  "  -it, --include-test <value>",
  "                            Include only test cases with the specified name. Can be used multiple times to specify multiple accepted names. Can be combined with -ic and -i.",
  "  -e, --exclude <value>     Exclude test cases with the specified name or category. Can be used multiple times to specify multiple criteria.Can be combined with -ic and -it.",
  "  -ec, --exclude-category <value>",
  "                            Exclude test cases with the specified category. Can be used multiple times to specify multiple accepted categories. Can be combined with -it and -i.",
  "  -et, --exclude-test <value>",
  "                            Exclude test cases with the specified name. Can be used multiple times to specify multiple accepted names. Can be combined with -ic and -i.",
  "  -g                        When used, the filters specified with -i[ct]/-e[ct] will be interpreted as regular expressions instead of literal strings.",
  "  -v, --verbose             Enable verbose logging output (using once = INFO level, using twice = DEBUG level).",
];

const PARSE_OPTIONS = {
  help: { type: "boolean", short: "h", default: false },
  recursive: { type: "boolean", short: "r", default: false },
  output: { type: "string", short: "o" },
  "dry-run": { type: "boolean", default: false },
  include: { type: "string", short: "i", multiple: true },
  "include-category": { type: "string", multiple: true },
  "include-test": { type: "string", multiple: true },
  exclude: { type: "string", short: "e", multiple: true },
  "exclude-category": { type: "string", multiple: true },
  "exclude-test": { type: "string", multiple: true },
  "regex-filters": { type: "boolean", short: "g", default: false },
  verbose: { type: "boolean", short: "v", multiple: true },
} as const;

function normalizeArgv(argv: string[]): string[] {
  return argv.map((arg) => DOUBLE_LETTER_SHORT_OPTION_NORMALIZATION.get(arg) ?? arg);
}

function printHelp(): void {
  console.log(HELP_TEXT.join("\n"));
}

function listOrNull(values: string[] | undefined): string[] | null {
  if (values === undefined || values.length === 0) {
    return null;
  }

  return values;
}

function parseCliArgumentsRaw(argv: string[]) {
  return parseArgs({
    args: normalizeArgv(argv),
    options: PARSE_OPTIONS,
    allowPositionals: true,
    strict: true,
  } as const);
}

function parseArguments(): CliArguments {
  /**
   * Parses the command-line arguments and performs basic validation a sanitization.
   */
  let parsed: ReturnType<typeof parseCliArgumentsRaw>;

  try {
    parsed = parseCliArgumentsRaw(process.argv.slice(2));
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(message);
    process.exit(2);
  }

  const parsedValues = parsed.values;

  if (parsedValues["help"]) {
    printHelp();
    process.exit(0);
  }

  if (parsed.positionals.length !== 1 || parsed.positionals[0] === undefined) {
    console.error("Exactly one positional argument (tests_dir) is required.");
    process.exit(2);
  }

  const args: CliArguments = {
    tests_dir: resolve(parsed.positionals[0]),
    recursive: parsedValues["recursive"],
    output: parsedValues["output"] ?? null,
    dry_run: parsedValues["dry-run"],
    include: listOrNull(parsedValues["include"]),
    include_category: listOrNull(parsedValues["include-category"]),
    include_test: listOrNull(parsedValues["include-test"]),
    exclude: listOrNull(parsedValues["exclude"]),
    exclude_category: listOrNull(parsedValues["exclude-category"]),
    exclude_test: listOrNull(parsedValues["exclude-test"]),
    verbose: parsedValues["verbose"]?.length ?? 0,
    regex_filters: parsedValues["regex-filters"],
  };

  // Check source directory
  if (!existsSync(args.tests_dir) || !lstatSync(args.tests_dir).isDirectory()) {
    console.error("The provided path is not a directory.");
    process.exit(1);
  }

  // Warn if the output file already exists
  if (args.output !== null) {
    const outputParent = dirname(args.output);
    if (!existsSync(outputParent)) {
      console.error("The parent directory of the output file does not exist.");
      process.exit(1);
    }

    if (existsSync(args.output)) {
      logger.warn("The output file will be overwritten: %s", args.output);
    }
  }

  return args;
}

function find_tests(test_dir: string, recursive: boolean): TestCaseDefinitionFile[] {
  const result: TestCaseDefinitionFile[] = [];
      for (const entry of readdirSync(test_dir)) {
        const full = join(test_dir, entry);
        if (lstatSync(full).isDirectory() && recursive) {
          result.push(...find_tests(full, recursive));
        }
        else if (entry.endsWith(".test")) {
          const name = basename(entry, ".test");
          const inFile = join(test_dir, name + ".in");
          const outFile = join(test_dir, name + ".out");
          result.push(new TestCaseDefinitionFile({
            name,
            test_source_path: full,
            stdin_file: existsSync(inFile) ? inFile : null,
            expected_stdout_file: existsSync(outFile) ? outFile : null,
          }));
        }
      }
      return result;
}

function parseTest(file: TestCaseDefinitionFile): TestCaseDefinition | UnexecutedReason {
  let content: string;
  try { content = readFileSync(file.test_source_path, "utf8"); }
  catch { return new UnexecutedReason(UnexecutedReasonCode.MALFORMED_TEST_CASE_FILE, "Cannot read"); }

  let description: string | null = null;
    let category: string | null = null;
    let points = 1;
    const parserCodes: number[] = [];
    const interpCodes: number[] = [];

    for (const line of content.split("\n")) {
      const t = line.trim();
      if (t.startsWith("***"))
        description = t.slice(3).trim();
      else if (t.startsWith("+++"))
        category = t.slice(3).trim();
      else if (t.startsWith("!C!")) 
        parserCodes.push(parseInt(t.slice(3).trim()));
      else if (t.startsWith("!I!"))
        interpCodes.push(parseInt(t.slice(3).trim()));
      else if (t.startsWith(">>>"))
        points = parseFloat(t.slice(3).trim());
    }

    if (!category) 
      return new UnexecutedReason(UnexecutedReasonCode.MALFORMED_TEST_CASE_FILE, "Missing category");

    let testType: TestCaseType;
    if (parserCodes.length > 0 && interpCodes.length === 0) 
      testType = TestCaseType.PARSE_ONLY;
    else if (interpCodes.length > 0 && parserCodes.length === 0)
      testType = TestCaseType.EXECUTE_ONLY;
    else if (parserCodes.length > 0 && interpCodes.length > 0)
      testType = TestCaseType.COMBINED;
    else 
      return new UnexecutedReason(UnexecutedReasonCode.CANNOT_DETERMINE_TYPE, "Cannot determine type");

    return new TestCaseDefinition({
        name: file.name, 
        test_source_path: file.test_source_path,
        stdin_file: file.stdin_file, 
        expected_stdout_file: file.expected_stdout_file,
        test_type: testType, 
        description, 
        category, 
        points,
        expected_parser_exit_codes: parserCodes.length > 0 ? parserCodes : null,
        expected_interpreter_exit_codes: interpCodes.length > 0 ? interpCodes : null,
      });
}

function matches(value: string | null, filters: string[] | null, regexFilters: boolean): boolean {
  if (!filters || filters.length === 0) 
    return false;
  if (value === null) 
    return false;
  return filters.some(f => regexFilters ? new RegExp(f.trim()).test(value) : value === f.trim());
}

function should_run(test: TestCaseDefinition, args: CliArguments): boolean {
  if (matches(test.name, args.exclude_test, args.regex_filters) || matches(test.category, args.exclude_category, args.regex_filters)) 
    return false;
  if (matches(test.name, args.exclude, args.regex_filters) || matches(test.category, args.exclude, args.regex_filters)) 
    return false;
  const hasInclude = (args.include?.length ?? 0) > 0 || (args.include_category?.length ?? 0) > 0 || (args.include_test?.length ?? 0) > 0;
  if (!hasInclude) return true;
  return matches(test.name, args.include_test, args.regex_filters) || matches(test.category, args.include_category, args.regex_filters) ||
         matches(test.name, args.include, args.regex_filters) || matches(test.category, args.include, args.regex_filters);
}

function get_source(file: TestCaseDefinitionFile): string {
    const lines = readFileSync(file.test_source_path, "utf8").split("\n");
    const idx = lines.findIndex(l => l.trim() === "");
    return idx === -1 ? "" : lines.slice(idx + 1).join("\n");
  }

function run_test(test: TestCaseDefinition): TestCaseReport {
    const SOL2XML = (process.env['SOL2XML'] || "/home/kubix/projects/ipp/sol2xml/sol_to_xml.py").trim();
    const INTERP = (process.env['INTERPRETER'] || "python3").trim();
    const INTERP_SCRIPT = (process.env['INTERPRETER_SCRIPT'] || "/home/.../tester/python/int/src/solint.py").trim();


    let xmlPath: string | null = null;
    let parserExitCode: number | null = null;
    let parserStdout: string | null = null;
    let parserStderr: string | null = null;
    let tmpDir: string | null = null;

    if (test.test_type === TestCaseType.PARSE_ONLY || test.test_type === TestCaseType.COMBINED) {
      const pr = spawnSync(SOL2XML, [], { input: get_source(test) });
      parserExitCode = pr.status ?? -1;
      parserStdout = pr.stdout?.toString("utf8") ?? null;
      parserStderr = pr.stderr?.toString("utf8") ?? null;

      if (!test.expected_parser_exit_codes!.includes(parserExitCode)) {
        return new TestCaseReport(TestResult.UNEXPECTED_PARSER_EXIT_CODE, parserExitCode, null, parserStdout, parserStderr, null, null, null);
      }
      if (test.test_type === TestCaseType.PARSE_ONLY) {
        return new TestCaseReport(TestResult.PASSED, parserExitCode, null, parserStdout, parserStderr, null, null, null);
      }
      tmpDir = mkdtempSync(join(tmpdir(), "sol26-"));
      xmlPath = join(tmpDir, "program.xml");
      writeFileSync(xmlPath, pr.stdout ?? Buffer.alloc(0));
    }

    if (test.test_type === TestCaseType.EXECUTE_ONLY) {
      xmlPath = test.test_source_path;
    }

    const interpArgs = [INTERP_SCRIPT, "--source", xmlPath!];
    if (test.stdin_file) interpArgs.push("--input", test.stdin_file);

    const ir = spawnSync(INTERP, interpArgs);
    if (tmpDir) rmSync(tmpDir, { recursive: true });

    const interpExitCode = ir.status ?? -1;
    const interpStdout = ir.stdout?.toString("utf8") ?? null;
    const interpStderr = ir.stderr?.toString("utf8") ?? null;

    if (!test.expected_interpreter_exit_codes!.includes(interpExitCode)) {
      return new TestCaseReport(TestResult.UNEXPECTED_INTERPRETER_EXIT_CODE, parserExitCode, interpExitCode, parserStdout, parserStderr, interpStdout, interpStderr, null);
    }

    if (test.expected_stdout_file !== null && interpExitCode === 0) {
      const diff = spawnSync("diff", ["-", test.expected_stdout_file], { input: interpStdout ?? "", encoding: "utf8" });
      if (diff.status !== 0) {
        return new TestCaseReport(TestResult.INTERPRETER_RESULT_DIFFERS, parserExitCode, interpExitCode, parserStdout, parserStderr, interpStdout, interpStderr, diff.stdout ?? null);
      }
    }

    return new TestCaseReport(TestResult.PASSED, parserExitCode, interpExitCode, parserStdout, parserStderr, interpStdout, interpStderr, null);
  }

function main(): void {
  /**
   * The main entry point for the SOL26 integration testing script.
   * It parses command-line arguments and executes the testing process.
   */

  // Set up logging
  // IPP: You do not have to use logging - but it is the recommended practice.
  //      See https://getpino.io/#/docs/api for more information.
  logger.level = "warn";

  // Parse the CLI arguments
  const args = parseArguments();

  // Enable debug or info logging if the verbose flag was set twice or once
  if (args.verbose >= 2) {
    logger.level = "debug";
  } else if (args.verbose === 1) {
    logger.level = "info";
  }

  const files = find_tests(args.tests_dir, args.recursive);
  const discovered: TestCaseDefinition[] = [];
  const unexecuted: Record<string, UnexecutedReason> = {};

  for (const file of files) {
      const result = parseTest(file);
      if (result instanceof TestCaseDefinition) 
        discovered.push(result);
      else 
        unexecuted[file.name] = result;
    }

  const categoryTotals: Record<string, { total: number; passed: number; tests: Record<string, TestCaseReport> }> = {};

  for (const test of discovered) {
    if (args.dry_run) continue;
 
    if (!should_run(test, args)) {
      unexecuted[test.name] = new UnexecutedReason(UnexecutedReasonCode.FILTERED_OUT);
      continue;
    }

    let test_report: TestCaseReport;
    try { test_report = run_test(test); }
    catch (e) { unexecuted[test.name] = new UnexecutedReason(UnexecutedReasonCode.CANNOT_EXECUTE, String(e)); continue; }

    const cat = test.category ?? "<unknown>";
    if (!categoryTotals[cat]) 
      categoryTotals[cat] = { total: 0, passed: 0, tests: {} };
    categoryTotals[cat].total += test.points;
    if (test_report.result === TestResult.PASSED) categoryTotals[cat].passed += test.points;
    categoryTotals[cat].tests[test.name] = test_report;

  }

  const results: Record<string, CategoryReport> = {};
  for (const [cat, data] of Object.entries(categoryTotals)) {
    results[cat] = new CategoryReport(data.total, data.passed, data.tests);
  }

  const report = new TestReport({
    discovered_test_cases: discovered,
    unexecuted,
    results: {},
  });
  
  writeResult(report, args.output);
  
}

main();
