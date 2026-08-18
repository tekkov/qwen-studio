#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{env, net::TcpStream, path::PathBuf, process::{Child, Command, Stdio}, sync::Mutex, thread, time::Duration};
use tauri::{Manager, RunEvent};

struct Backend(Mutex<Option<Child>>);

fn python_commands() -> Vec<(String, Vec<String>)> {
    if let Some(configured) = env::var_os("QWEN_PYTHON") {
        return vec![(configured.to_string_lossy().into_owned(), vec![])];
    }
    if cfg!(target_os = "windows") {
        vec![("py".into(), vec!["-3".into()]), ("python".into(), vec![])]
    } else {
        vec![("python3".into(), vec![]), ("python".into(), vec![])]
    }
}

fn start_backend(app: &tauri::AppHandle) -> Result<Child, String> {
    let root: PathBuf = if cfg!(debug_assertions) {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
    } else {
        let resources = app.path().resource_dir().map_err(|e| e.to_string())?;
        let bundled = resources.join("_up_");
        if bundled.join("server.py").is_file() { bundled } else { resources }
    };
    let mut last_error = None;
    for (python, prefix) in python_commands() {
        let mut command = Command::new(&python);
        command.args(prefix).arg(root.join("server.py")).current_dir(&root).env("QWEN_PORT", "8000").stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        match command.spawn() {
            Ok(child) => return Ok(child),
            Err(error) => last_error = Some(format!("{python}: {error}")),
        }
    }
    Err(format!("Could not start Python backend: {}", last_error.unwrap_or_else(|| "no Python command was available".into())))
}

fn run() {
    tauri::Builder::default().plugin(tauri_plugin_dialog::init()).setup(|app| {
        let child = start_backend(app.handle())?;
        app.manage(Backend(Mutex::new(Some(child))));
        if env::var_os("QWEN_SMOKE_TEST").is_some() {
            let handle = app.handle().clone();
            thread::spawn(move || {
                for _ in 0..20 {
                    if TcpStream::connect("127.0.0.1:8000").is_ok() { handle.exit(0); return; }
                    thread::sleep(Duration::from_millis(250));
                }
                handle.exit(2);
            });
        }
        Ok(())
    }).build(tauri::generate_context!()).expect("error while running Qwen Studio").run(|app, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = app.try_state::<Backend>() {
                if let Ok(mut child) = state.0.lock() { if let Some(process) = child.as_mut() { let _ = process.kill(); } }
            }
        }
    });
}

fn main() { run(); }
