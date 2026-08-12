# frozen_string_literal: true

# Synchronize release metadata and the platform-specific TAPL MCP runtime in the
# Homebrew formulas checked out by the release workflow.

require "fileutils"
require "optparse"
require "pathname"
require "rubygems/version"

options = {}
parser = OptionParser.new do |opts|
  opts.on("--pre-formula PATH", "Update or create the rolling prerelease formula") do |path|
    options[:pre_formula] = path
  end
  opts.on("--pre-alias PATH", "Create the taplctl@pre alias for the prerelease formula") do |path|
    options[:pre_alias] = path
  end
end

files = parser.parse(ARGV)
raise "Pass a Homebrew formula path or --pre-formula PATH" if files.empty? && !options[:pre_formula]
raise "--pre-alias requires --pre-formula" if options[:pre_alias] && !options[:pre_formula]

version = ENV.fetch("RELEASE_VERSION")
wheel_url = ENV.fetch("WHEEL_URL")
wheel_sha256 = ENV.fetch("WHEEL_SHA256")

runtime_assets = {
  "macos" => {
    "arm" => [
      ENV.fetch("MCP_RUNTIME_MACOS_ARM64_URL"),
      ENV.fetch("MCP_RUNTIME_MACOS_ARM64_SHA256"),
    ],
    "intel" => [
      ENV.fetch("MCP_RUNTIME_MACOS_X86_64_URL"),
      ENV.fetch("MCP_RUNTIME_MACOS_X86_64_SHA256"),
    ],
  },
  "linux" => {
    "arm" => [
      ENV.fetch("MCP_RUNTIME_LINUX_ARM64_URL"),
      ENV.fetch("MCP_RUNTIME_LINUX_ARM64_SHA256"),
    ],
    "intel" => [
      ENV.fetch("MCP_RUNTIME_LINUX_X86_64_URL"),
      ENV.fetch("MCP_RUNTIME_LINUX_X86_64_SHA256"),
    ],
  },
}.freeze

RUNTIME_BEGIN = "# taplctl-mcp-runtime-begin"
RUNTIME_END = "# taplctl-mcp-runtime-end"
SMOKE_BEGIN = "# taplctl-mcp-smoke-begin"
SMOKE_END = "# taplctl-mcp-smoke-end"
PRE_FORMULA_TEMPLATE = ENV["PRE_FORMULA_TEMPLATE"]
PEP_440_VERSION_PATTERN = '\\d+\\.\\d+\\.\\d+(?:(?:a|b|rc)\\d+)?'
FORMULA_CONFLICTS = {
  "taplctl" => %w[taplctl-semantic taplctl-pre],
  "taplctl-semantic" => %w[taplctl taplctl-pre],
  "taplctl-pre" => %w[taplctl taplctl-semantic],
}.freeze

def replacement_line(line, content)
  line.end_with?("\n") ? "#{content}\n" : content
end

def find_block_end(lines, start_index, indent)
  ((start_index + 1)...lines.length).find do |index|
    lines[index].match?(/^#{Regexp.escape(indent)}end\s*$/)
  end
end

def viewer_service_block(indent)
  [
    "#{indent}service do\n",
    "#{indent}  run [opt_bin/\"taplctl\", \"viewer\"]\n",
    "#{indent}  keep_alive true\n",
    "#{indent}  restart_delay 5\n",
    "#{indent}  log_path var/\"log/taplctl-viewer.log\"\n",
    "#{indent}  error_log_path var/\"log/taplctl-viewer.log\"\n",
    "#{indent}end\n",
  ]
end

def upsert_viewer_service_block(lines, indent)
  service_start = lines.index { |line| line.match?(/^#{Regexp.escape(indent)}service\s+do\s*$/) }
  if service_start
    service_end = find_block_end(lines, service_start, indent)
    raise "Could not find end of service block" unless service_end

    lines[service_start..service_end] = viewer_service_block(indent)
    return
  end

  install_start = lines.index { |line| line.match?(/^#{Regexp.escape(indent)}def install\s*$/) }
  raise "Could not find install block for service insertion" unless install_start

  install_end = find_block_end(lines, install_start, indent)
  raise "Could not find end of install block for service insertion" unless install_end

  insert_index = install_end + 1
  block = ["\n", *viewer_service_block(indent)]
  block << "\n" unless lines[insert_index]&.match?(/^\s*$/)
  lines.insert(insert_index, *block)
end

def runtime_resource_block(indent, assets)
  lines = ["#{indent}#{RUNTIME_BEGIN}\n"]
  { "macos" => "on_macos", "linux" => "on_linux" }.each do |os, os_dsl|
    lines << "#{indent}#{os_dsl} do\n"
    { "arm" => "on_arm", "intel" => "on_intel" }.each do |arch, arch_dsl|
      url, sha256 = assets.fetch(os).fetch(arch)
      lines.concat(
        [
          "#{indent}  #{arch_dsl} do\n",
          "#{indent}    resource \"mcp-runtime\" do\n",
          "#{indent}      url \"#{url}\"\n",
          "#{indent}      sha256 \"#{sha256}\"\n",
          "#{indent}    end\n",
          "#{indent}  end\n",
        ],
      )
    end
    lines << "#{indent}end\n"
  end
  lines << "#{indent}#{RUNTIME_END}\n"
  lines
end

def upsert_marked_block(lines, begin_marker, end_marker, replacement, insert_index)
  start_index = lines.index { |line| line.strip == begin_marker }
  end_index = lines.index { |line| line.strip == end_marker }
  if start_index || end_index
    raise "Incomplete marked block #{begin_marker}" unless start_index && end_index && end_index >= start_index

    lines[start_index..end_index] = replacement
  else
    lines.insert(insert_index, *replacement, "\n")
  end
end

def install_block(indent)
  [
    "#{indent}def install\n",
    "#{indent}  wheel = Pathname.glob(\"*.whl\").first\n",
    "#{indent}  raise \"Could not find taplctl wheel\" unless wheel\n",
    "\n",
    "#{indent}  wheelhouse = buildpath/\"wheelhouse\"\n",
    "#{indent}  wheelhouse.mkpath\n",
    "#{indent}  resource(\"mcp-runtime\").stage { wheelhouse.install Dir[\"*.whl\"] }\n",
    "#{indent}  runtime_packages = wheelhouse.glob(\"*.whl\").map do |runtime_wheel|\n",
    "#{indent}    runtime_wheel.basename.to_s.split(\"-\", 2).first.tr(\"_\", \"-\").downcase\n",
    "#{indent}  end\n",
    "#{indent}  resources.each do |resource|\n",
    "#{indent}    next if resource.name == \"mcp-runtime\"\n",
    "#{indent}    next if runtime_packages.include?(resource.name.tr(\"_\", \"-\").downcase)\n",
    "\n",
    "#{indent}    resource.stage { wheelhouse.install Dir[\"*.whl\"] }\n",
    "#{indent}  end\n",
    "\n",
    "#{indent}  dependency_wheels = wheelhouse.glob(\"*.whl\")\n",
    "#{indent}  raise \"Could not find dependency wheels\" if dependency_wheels.empty?\n",
    "#{indent}  virtualenv_create(libexec, \"python3.12\", system_site_packages: false)\n",
    "#{indent}  system \"python3.12\", \"-m\", \"pip\", \"--python=\#{libexec}/bin/python\", \"install\",\n",
    "#{indent}         \"--no-index\", \"--no-deps\", \"--no-compile\", *dependency_wheels\n",
    "#{indent}  system \"python3.12\", \"-m\", \"pip\", \"--python=\#{libexec}/bin/python\", \"install\",\n",
    "#{indent}         \"--no-index\", \"--no-deps\", \"--no-compile\", wheel\n",
    "#{indent}  bin.install_symlink libexec/\"bin/taplctl\"\n",
    "#{indent}  bin.install_symlink libexec/\"bin/tapl-mcp\"\n",
    "#{indent}  bin.install_symlink libexec/\"bin/tapl-hook\"\n",
    "#{indent}end\n",
  ]
end

def smoke_test_block(indent)
  [
    "#{indent}  #{SMOKE_BEGIN}\n",
    "#{indent}  assert_path_exists bin/\"tapl-mcp\"\n",
    "#{indent}  assert_path_exists bin/\"tapl-hook\"\n",
    "#{indent}  system libexec/\"bin/python\", \"-c\",\n",
    "#{indent}         \"from mcp.server import MCPServer; from taplctl.mcp_server import create_server; assert create_server()\"\n",
    "#{indent}  #{SMOKE_END}\n",
  ]
end

def formula_version(lines, file)
  version_line = lines.find { |line| line.match?(/^\s*version\s+["'][^"']+["']/) }
  raise "Could not find version in #{file}" unless version_line

  Gem::Version.new(version_line[/^\s*version\s+["']([^"']+)["']/, 1])
rescue ArgumentError => error
  raise "Could not parse version in #{file}: #{error.message}"
end

def normalize_formula_class(lines, class_name, file)
  class_index = lines.index { |line| line.match?(/^class\s+\S+\s+<\s+Formula\s*$/) }
  raise "Could not find formula class in #{file}" unless class_index

  lines[class_index] = replacement_line(lines[class_index], "class #{class_name} < Formula")
end

def normalize_formula_conflicts(lines, formula_name)
  conflicts = FORMULA_CONFLICTS[formula_name]
  return unless conflicts

  known_formula_names = FORMULA_CONFLICTS.keys
  lines.reject! do |line|
    match = line.match(/^\s*conflicts_with\s+["']([^"']+)["']/)
    match && known_formula_names.include?(match[1])
  end

  dependency_index = lines.rindex { |line| line.match?(/^\s*depends_on\b/) }
  raise "Could not find dependency block for #{formula_name}" unless dependency_index

  insert_index = dependency_index + 1
  lines.delete_at(insert_index) while lines[insert_index]&.strip == ""
  conflict_lines = conflicts.map do |conflict|
    %(  conflicts_with "#{conflict}", because: "both install the taplctl executable"\n)
  end
  lines.insert(insert_index, "\n", *conflict_lines, "\n")
end

def normalize_version_test(lines)
  stable_pattern = '\\d+\\.\\d+\\.\\d+\\z'
  lines.map! do |line|
    next line unless line.include?("assert_match") && line.include?("taplctl")

    line.sub(stable_pattern, "#{PEP_440_VERSION_PATTERN}\\z")
  end
end

def update_formula(file, version, wheel_url, wheel_sha256, runtime_assets, formula_name: nil, class_name: nil)
  lines = File.readlines(file)

  normalize_formula_class(lines, class_name, file) if class_name
  normalize_formula_conflicts(lines, formula_name) if formula_name
  normalize_version_test(lines)

  incoming_version = Gem::Version.new(version)
  current_version = formula_version(lines, file)
  if incoming_version < current_version
    warn "Skipping #{file}: #{version} is older than #{current_version}"
    File.write(file, lines.join)
    return false
  end

  version_index = lines.index { |line| line.match?(/^(\s*)version\s+[\"'][^\"']+[\"'](.*)$/) }
  raise "Could not update version in #{file}" unless version_index

  version_match = lines[version_index].match(/^(\s*)version\s+[\"'][^\"']+[\"'](.*)$/)
  lines[version_index] = replacement_line(
    lines[version_index],
    "#{version_match[1]}version \"#{version}\"#{version_match[2]}",
  )

  url_index = lines.index { |line| line.match?(/^(\s*)url\s+[\"'][^\"']+[\"'](.*)$/) }
  raise "Could not update url in #{file}" unless url_index

  url_match = lines[url_index].match(/^(\s*)url\s+[\"'][^\"']+[\"'](.*)$/)
  url_indent = url_match[1]
  lines[url_index] = replacement_line(lines[url_index], "#{url_indent}url \"#{wheel_url}\"")

  sha_index = lines.index { |line| line.match?(/^#{Regexp.escape(url_indent)}sha256\b/) }
  sha_line = "#{url_indent}sha256 \"#{wheel_sha256}\""
  if sha_index
    lines[sha_index] = replacement_line(lines[sha_index], sha_line)
  else
    sha_insert_index = version_index > url_index ? version_index + 1 : url_index + 1
    lines.insert(sha_insert_index, "#{sha_line}\n")
  end

  install_start = lines.index { |line| line.match?(/^(\s*)def install\s*$/) }
  raise "Could not find install block in #{file}" unless install_start

  indent = lines[install_start].match(/^(\s*)/)[1]
  runtime_lines = runtime_resource_block(indent, runtime_assets)
  upsert_marked_block(lines, RUNTIME_BEGIN, RUNTIME_END, runtime_lines, install_start)

  install_start = lines.index { |line| line.match?(/^#{Regexp.escape(indent)}def install\s*$/) }
  install_end = find_block_end(lines, install_start, indent)
  raise "Could not find end of install block in #{file}" unless install_end

  lines[install_start..install_end] = install_block(indent)
  upsert_viewer_service_block(lines, indent)

  test_start = lines.index { |line| line.match?(/^#{Regexp.escape(indent)}test\s+do\s*$/) }
  raise "Could not find test block in #{file}" unless test_start

  smoke_lines = smoke_test_block(indent)
  upsert_marked_block(lines, SMOKE_BEGIN, SMOKE_END, smoke_lines, test_start + 1)

  File.write(file, lines.join)
  true
end

files.each do |file|
  update_formula(
    file,
    version,
    wheel_url,
    wheel_sha256,
    runtime_assets,
    formula_name: File.basename(file, ".rb"),
  )
end

if options[:pre_formula]
  pre_formula = options[:pre_formula]
  unless File.exist?(pre_formula)
    template = PRE_FORMULA_TEMPLATE || files.first
    raise "PRE_FORMULA_TEMPLATE or a positional formula is required to create #{pre_formula}" unless template
    raise "Could not find prerelease formula template: #{template}" unless File.file?(template)

    FileUtils.mkdir_p(File.dirname(pre_formula))
    FileUtils.cp(template, pre_formula)
  end

  update_formula(
    pre_formula,
    version,
    wheel_url,
    wheel_sha256,
    runtime_assets,
    formula_name: "taplctl-pre",
    class_name: "TaplctlPre",
  )

  if options[:pre_alias]
    pre_alias = options[:pre_alias]
    FileUtils.mkdir_p(File.dirname(pre_alias))
    relative_target = Pathname.new(File.expand_path(pre_formula)).relative_path_from(
      Pathname.new(File.expand_path(File.dirname(pre_alias))),
    ).to_s
    if File.symlink?(pre_alias)
      File.unlink(pre_alias) unless File.readlink(pre_alias) == relative_target
    elsif File.exist?(pre_alias)
      raise "Refusing to replace non-symlink prerelease alias: #{pre_alias}"
    end
    File.symlink(relative_target, pre_alias) unless File.symlink?(pre_alias)
  end
end
