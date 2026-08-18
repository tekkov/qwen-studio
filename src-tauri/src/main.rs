#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use std::{
    collections::HashMap,
    env,
    fs::{self, OpenOptions},
    io::Write,
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{atomic::{AtomicBool, Ordering}, Mutex},
    thread,
    time::Duration,
};
use tauri::{Manager, RunEvent, State};
use uuid::Uuid;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendConfig {
    url: String,
    token: String,
    port: u16,
}

#[derive(Clone)]
struct LaunchSpec {
    root: PathBuf,
    environment: HashMap<String, String>,
    config: BackendConfig,
    log_path: PathBuf,
}

struct Backend {
    child: Mutex<Option<Child>>,
    stopping: AtomicBool,
    launch: LaunchSpec,
}

#[tauri::command]
fn backend_config(config: State<'_, BackendConfig>) -> BackendConfig {
    config.inner().clone()
}

fn hide_console(command: &mut Command) {
    #[cfg(target_os = "windows")]
    command.creation_flags(CREATE_NO_WINDOW);
}

fn append_log(path: &Path, message: &str) {
    if let Some(parent) = path.parent() { let _ = fs::create_dir_all(parent); }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{message}");
    }
}

fn load_env_file(path: &Path, values: &mut HashMap<String, String>) {
    let Ok(contents) = fs::read_to_string(path) else { return };
    for line in contents.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') { continue; }
        let Some((key, raw)) = line.split_once('=') else { continue };
        let key = key.trim();
        if key.is_empty() || values.contains_key(key) || env::var_os(key).is_some() { continue; }
        let value = raw.trim().trim_matches(|character| character == '\'' || character == '"');
        values.insert(key.to_string(), value.to_string());
    }
}

fn local_environment(root: &Path, app_data: &Path) -> HashMap<String, String> {
    let mut values = HashMap::new();
    load_env_file(&root.join(".env"), &mut values);
    load_env_file(&app_data.join(".env"), &mut values);
    values
}

fn environment_value(values: &HashMap<String, String>, key: &str) -> Option<String> {
    env::var(key).ok().or_else(|| values.get(key).cloned())
}

fn python_commands(values: &HashMap<String, String>) -> Vec<(String, Vec<String>)> {
    if let Some(configured) = environment_value(values, "QWEN_PYTHON") {
        return vec![(configured, vec![])];
    }
    if cfg!(target_os = "windows") {
        vec![("py".into(), vec!["-3".into()]), ("python".into(), vec![])]
    } else {
        vec![("python3".into(), vec![]), ("python".into(), vec![])]
    }
}

fn resource_root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) { return Ok(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")); }
    let resources = app.path().resource_dir().map_err(|error| error.to_string())?;
    let bundled = resources.join("_up_");
    Ok(if bundled.join("server.py").is_file() { bundled } else { resources })
}

fn choose_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0)).map_err(|error| format!("Could not reserve a local port: {error}"))?;
    listener.local_addr().map(|address| address.port()).map_err(|error| error.to_string())
}

fn start_backend(spec: &LaunchSpec) -> Result<Child, String> {
    let mut last_error = None;
    for (python, prefix) in python_commands(&spec.environment) {
        let stdout = OpenOptions::new().create(true).append(true).open(&spec.log_path).ok();
        let stderr = stdout.as_ref().and_then(|file| file.try_clone().ok());
        let mut command = Command::new(&python);
        command
            .args(prefix)
            .arg(spec.root.join("server.py"))
            .current_dir(&spec.root)
            .envs(&spec.environment)
            .env("QWEN_PORT", spec.config.port.to_string())
            .env("QWEN_API_TOKEN", &spec.config.token)
            .stdin(Stdio::null())
            .stdout(stdout.map(Stdio::from).unwrap_or_else(Stdio::null))
            .stderr(stderr.map(Stdio::from).unwrap_or_else(Stdio::null));
        hide_console(&mut command);
        match command.spawn() {
            Ok(child) => {
                append_log(&spec.log_path, &format!("Started Python backend with {python} on port {}.", spec.config.port));
                return Ok(child);
            }
            Err(error) => last_error = Some(format!("{python}: {error}")),
        }
    }
    Err(format!("Could not start Python backend: {}", last_error.unwrap_or_else(|| "no Python command was available".into())))
}

fn ollama_commands(values: &HashMap<String, String>) -> Vec<String> {
    if let Some(configured) = environment_value(values, "OLLAMA_COMMAND") { return vec![configured]; }
    let mut commands = Vec::new();
    if cfg!(target_os = "windows") {
        if let Ok(local) = env::var("LOCALAPPDATA") { commands.push(format!(r"{}\Programs\Ollama\ollama.exe", local)); }
        if let Ok(programs) = env::var("ProgramFiles") { commands.push(format!(r"{}\Ollama\ollama.exe", programs)); }
    } else if cfg!(target_os = "macos") {
        commands.push("/Applications/Ollama.app/Contents/Resources/ollama".into());
        commands.push("/usr/local/bin/ollama".into());
        commands.push("/opt/homebrew/bin/ollama".into());
    }
    commands.push("ollama".into());
    commands
}

fn ensure_ollama(values: HashMap<String, String>, log_path: PathBuf) {
    if environment_value(&values, "OLLAMA_URL").is_some_and(|url| !url.contains("127.0.0.1:11434") && !url.contains("localhost:11434")) {
        append_log(&log_path, "Custom OLLAMA_URL configured; automatic local Ollama startup skipped.");
        return;
    }
    if TcpStream::connect_timeout(&"127.0.0.1:11434".parse().unwrap(), Duration::from_millis(300)).is_ok() { return; }
    for executable in ollama_commands(&values) {
        if executable.contains(['\\', '/']) && !Path::new(&executable).is_file() { continue; }
        let mut command = Command::new(&executable);
        command.arg("serve").envs(&values).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        hide_console(&mut command);
        match command.spawn() {
            Ok(_) => {
                append_log(&log_path, &format!("Started Ollama with {executable}."));
                for _ in 0..60 {
                    if TcpStream::connect_timeout(&"127.0.0.1:11434".parse().unwrap(), Duration::from_millis(300)).is_ok() { return; }
                    thread::sleep(Duration::from_millis(500));
                }
                append_log(&log_path, "Ollama was launched but did not become ready within 30 seconds.");
                return;
            }
            Err(error) => append_log(&log_path, &format!("Could not launch Ollama with {executable}: {error}")),
        }
    }
    append_log(&log_path, "Ollama was not found. Install it or set OLLAMA_COMMAND.");
}

fn monitor_backend(app: tauri::AppHandle) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(1));
        let state = app.state::<Backend>();
        if state.stopping.load(Ordering::SeqCst) { break; }
        let restart = {
            let mut child = state.child.lock().expect("backend state lock poisoned");
            match child.as_mut() {
                Some(process) => matches!(process.try_wait(), Ok(Some(_)) | Err(_)),
                None => true,
            }
        };
        if restart {
            append_log(&state.launch.log_path, "Backend exited unexpectedly; restarting.");
            let replacement = start_backend(&state.launch).ok();
            if let Ok(mut child) = state.child.lock() { *child = replacement; }
        }
    });
}

fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") { let _ = window.show(); let _ = window.set_focus(); }
        }))
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![backend_config])
        .setup(|app| {
            let root = resource_root(app.handle())?;
            let app_data = app.path().app_data_dir().map_err(|error| error.to_string())?;
            fs::create_dir_all(&app_data).map_err(|error| error.to_string())?;
            let environment = local_environment(&root, &app_data);
            let port = choose_port()?;
            let config = BackendConfig { url: format!("http://127.0.0.1:{port}"), token: Uuid::new_v4().simple().to_string(), port };
            let launch = LaunchSpec { root, environment: environment.clone(), config: config.clone(), log_path: app_data.join("qwen-backend.log") };
            let child = start_backend(&launch)?;
            app.manage(config.clone());
            app.manage(Backend { child: Mutex::new(Some(child)), stopping: AtomicBool::new(false), launch });
            monitor_backend(app.handle().clone());
            let ollama_log = app_data.join("qwen-backend.log");
            thread::spawn(move || ensure_ollama(environment, ollama_log));
            if env::var_os("QWEN_SMOKE_TEST").is_some() {
                let handle = app.handle().clone();
                thread::spawn(move || {
                    for _ in 0..40 {
                        if TcpStream::connect(("127.0.0.1", config.port)).is_ok() { handle.exit(0); return; }
                        thread::sleep(Duration::from_millis(250));
                    }
                    handle.exit(2);
                });
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running Qwen Studio")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app.try_state::<Backend>() {
                    state.stopping.store(true, Ordering::SeqCst);
                    if let Ok(mut child) = state.child.lock() {
                        if let Some(process) = child.as_mut() { let _ = process.kill(); let _ = process.wait(); }
                        *child = None;
                    }
                }
            }
        });
}

fn main() { run(); }
