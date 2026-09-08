# Репозиторий на GitHub: настройка и доступы

## Почему GitHub, а не GitLab

Приватные репозитории бесплатны и без лимита на коллабораторов; Actions хватает
с запасом; у всех уже есть аккаунты; жюри ожидает GitHub; `gh` CLI и интеграции
с Claude Code / Codex работают из коробки. GitLab дал бы то же самое без плюсов.

## Что делает Антон (один раз, ~15 минут)

### 1. Установить `gh`, если ещё нет

```bash
brew install gh && gh auth login
```
Выбрать `GitHub.com` → `HTTPS` → `Login with a web browser`.

### 2. Создать приватный репозиторий и запушить

Из папки `/Users/antonzagitov/Work/khakaton2026/repo`:

```bash
gh repo create trendradar --private --source=. --remote=origin --push
```

Репозиторий сразу приватный: видят его только владелец и приглашённые.

### 3. Пригласить Михаила и Константина

Нужны их GitHub-логины (не почта — логин, вида `mikhail-xxx`).

```bash
gh api -X PUT repos/:owner/trendradar/collaborators/ЛОГИН_МИХАИЛА -f permission=push
gh api -X PUT repos/:owner/trendradar/collaborators/ЛОГИНА_КОНСТАНТИНА -f permission=push
```

`permission=push` — право читать, пушить ветки и открывать PR, но не удалять
репозиторий и не менять настройки. Ровно то, что нужно.

Им придёт приглашение на почту — его надо принять, иначе доступа не будет.

### 4. Защитить `main`

```bash
gh api -X PUT repos/:owner/trendradar/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["ci"]},
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

Это запрещает пуш напрямую в `main` и мерж с красным CI. Ревью не делаем
обязательным — на хакатоне это тормозит, честной истории PR достаточно.

### 5. Проверить, что всё встало

```bash
gh repo view --web
gh api repos/:owner/trendradar/collaborators --jq '.[].login'
```

## Что делают Михаил и Константин (~5 минут)

### 1. Принять приглашение
Письмо на почту от GitHub, либо https://github.com/notifications → Invitations.

### 2. Настроить доступ по SSH (один раз)

```bash
ssh-keygen -t ed25519 -C "почта@example.com"
cat ~/.ssh/id_ed25519.pub
```
Скопировать вывод → https://github.com/settings/keys → **New SSH key** → вставить.

Проверить:
```bash
ssh -T git@github.com
```
Должно ответить `Hi ЛОГИН! You've successfully authenticated`.

### 3. Клонировать

```bash
git clone git@github.com:ЛОГИН_АНТОНА/trendradar.git
cd trendradar
```

### 4. Поставить окружение

```bash
brew install uv          # macOS
# или: curl -LsSf https://astral.sh/uv/install.sh | sh   (Linux/WSL)
uv sync
```

Проверка, что всё встало:
```bash
make check
```

### 5. Прочитать три файла перед первым коммитом

1. `AGENTS.md` — что за проект и что нельзя трогать
2. `team/WORKFLOW.md` — как работаем с ветками
3. `team/PROMPT-<своё-имя>.md` — личный бриф со списком задач

## Как передавать большие данные

Полный корпус (десятки ГБ) в git не едет. Схема такая:

- в репозитории лежит **золотой снапшот** `data/index/golden/` (~50 МБ) —
  на нём идут разработка, тесты и CI;
- полные корпуса выкладываем в **GitHub Releases** (до 2 ГБ на файл):

```bash
# выложить
gh release create corpus-ai-2026 data/corpus/artificial-intelligence/works.parquet \
   --title "Корпус: ИИ, 2015-2026" --notes "Собран 10.09.2026, 412k документов"

# забрать
gh release download corpus-ai-2026 -D data/corpus/artificial-intelligence/
```

То же самое делает `make pull-corpus`.

## Если что-то пошло не так

| Симптом | Причина | Что делать |
|---|---|---|
| `Permission denied (publickey)` | SSH-ключ не добавлен на GitHub | шаг 2 выше |
| `remote: Repository not found` | приглашение не принято | проверить почту |
| CI красный на чужом файле | залез в чужую папку | откатить эти файлы, см. `WORKFLOW.md` |
| Конфликт в `contracts/` или `pyproject.toml` | двое полезли в общий файл | не решать самому, писать Антону |
