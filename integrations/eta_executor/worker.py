"""python -m integrations.eta_executor.worker; default is NO final submissions."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime,timezone
from .client import CRMClient
from .portal import Portal,PortalStop


def private_write(path,data):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data));os.chmod(tmp,0o600)
    with tmp.open('rb') as f:os.fsync(f.fileno())
    tmp.replace(path)


async def run_once(client,job,root,mapping,browser,sessions):
    app_id=job['application_id'];folder=root/app_id/job['packet']['batch_id'];folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    journal=folder/'state.json';state=json.loads(journal.read_text()) if journal.exists() else {}
    entry=job['packet']['applicants'][0]
    if state.get('data_sha256') not in (None,entry['data_sha256']):
        # Never silently repurpose a context previously used for different identity data.
        raise PortalStop('Сохранённая сессия относится к другой версии. Нужна ручная проверка исполнителя.')
    state['data_sha256']=entry['data_sha256'];private_write(journal,state)
    current=job['current_result']
    row={k:v for k,v in current.items() if k not in ('approval_notice','authorization_token')}
    row.update(application_id=app_id,tourist_id=entry['tourist_id'],data_sha256=entry['data_sha256'],updated_at=datetime.now(timezone.utc).isoformat())
    lease={'lease_token':job['lease_token']}
    async def heartbeat():
        while True:
            await asyncio.sleep(45)
            try:await asyncio.to_thread(client.post,f'applications/{app_id}/heartbeat/',lease)
            except Exception:return  # begin-submission will still require an active lease
    pulse=asyncio.create_task(heartbeat())
    try:
        retained=app_id in sessions
        if job['action']=='submit' and not retained:
            raise PortalStop('Браузерная сессия была потеряна. Сначала повторно получите и подтвердите сводку; подача не начата.')
        if retained:context=sessions[app_id]
        else:
            context=await browser.chromium.launch_persistent_context(str(folder/'chromium'),headless=os.getenv('ETA_HEADLESS','1')=='1',accept_downloads=False)
            sessions[app_id]=context
        try:
            page=context.pages[0] if context.pages else await context.new_page()
            driver=Portal(page,mapping,dry_run=os.getenv('ETA_ALLOW_SUBMIT','0')!='1')
            await context.route('**/*',driver.guard)
            # Closing Chromium retains cookies/storage, not arbitrary JS heap/DOM.
            # Restore only this job's last URL and verify its markers/values anew.
            if page.url=='about:blank' and state.get('url'):
                driver.check_url(state['url']);await page.goto(state['url'],wait_until='domcontentloaded')
            action=job['action']
            if action=='prepare':
                if state.get('submission_attempted') or job.get('submission_started'):raise PortalStop('Подача уже начиналась. Доступна только проверка статуса.')
                row.update(await driver.prepare(entry['data']),stage='awaiting_confirmation',portal_status='Actual portal summary',stop_reason='')
            elif action=='submit':
                if state.get('submission_attempted') or job.get('submission_started'):raise PortalStop('Подача уже начиналась. Повтор запрещён.')
                async def begin(review,conditions,fee):
                    # Durable local fence before any network request/final click.
                    state['submission_attempted']=True;state['url']=page.url;private_write(journal,state)
                    response=await asyncio.to_thread(client.post,f'applications/{app_id}/begin-submission/',{**lease,'review_sha256':review,'conditions_sha256':conditions,'fee':fee})
                    state['authorization']=response['authorization'];private_write(journal,state)
                    return response['authorization']
                row.update(await driver.submit(entry['data'],begin),stop_reason='')
            elif action=='status':
                row.update(await driver.status(job['application_number'],entry['data']))
                authorization=job.get('authorization') or state.get('authorization')
                if authorization:row['authorization_token']=authorization['authorization_token']
                if row.get('approval_notice'):row['approval_notice'].update(application_id=app_id,tourist_id=entry['tourist_id'],application_number=job['application_number'])
            else:raise PortalStop('Неизвестное действие исполнителя.')
        except PortalStop as exc:
            row.update(stage='error',stop_reason=str(exc),captcha_required=exc.captcha,portal_rules_changed=exc.changed,unconfirmed_fields=[])
            if state.get('submission_attempted') or job.get('submission_started'):row['submission_uncertain']=True
        except Exception:
            row.update(stage='error',stop_reason='Сбой браузера. Проверьте сохранённую сессию; повторная подача автоматически не выполняется.',submission_uncertain=bool(state.get('submission_attempted') or job.get('submission_started')))
        finally:
            # URL is private local state, never logged or returned in CRM messages.
            state['url']=page.url;private_write(journal,state)
    except PortalStop as exc:
        row.update(stage='error',stop_reason=str(exc))
    except Exception:
        row.update(stage='error',stop_reason='Не удалось открыть браузер исполнителя. Нужна проверка сервиса.')
    finally:pulse.cancel()
    row['updated_at']=datetime.now(timezone.utc).isoformat()
    result={k:v for k,v in job['packet'].items() if k in ('batch_id','contract_id','contract_exchange_id','handoff_token')}
    result.update(schema='aborigen.sri-lanka-eta.result.v1',results=[row])
    await asyncio.to_thread(client.post,f'applications/{app_id}/result/',{**lease,'result':result})
    if row.get('stage') in ('approved','submitted','under_review','referral') and app_id in sessions:
        await sessions.pop(app_id).close()


async def main():
    os.umask(0o077)
    client=CRMClient(os.environ['ETA_CRM_URL'],os.environ['ETA_WORKER_TOKEN'],os.environ['ETA_WORKER_ID'])
    root=Path(os.environ.get('ETA_STATE_DIR','/var/lib/eta-executor'));root.mkdir(parents=True,exist_ok=True,mode=0o700)
    mapping=json.loads(Path(os.environ['ETA_PORTAL_MAP']).read_text())
    from playwright.async_api import async_playwright
    sessions={}
    async with async_playwright() as browser:
        while True:
            try:
                if sessions:
                    keep=(await asyncio.to_thread(client.post,'sessions/',{'applications':list(sessions)}))['keep']
                    for key in list(sessions):
                        if key not in keep:await sessions.pop(key).close()
                # Each retained form stays in a live browser until confirmation.
                # Limit memory, rather than silently evict a pending session.
                job=(await asyncio.to_thread(client.post,'claim/',{'retained_sessions':list(sessions),'capacity':len(sessions)<int(os.getenv('ETA_MAX_SESSIONS','3'))}))['job']
                if job:await run_once(client,job,root,mapping,browser,sessions)
                else:await asyncio.sleep(10)
            except Exception:
                print('ETA executor stopped current attempt; inspect CRM status.',flush=True)
                await asyncio.sleep(15)


if __name__=='__main__':asyncio.run(main())
