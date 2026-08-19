import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '@/api/client';
import StaffdeckIcon from '@/components/StaffdeckIcon';
import { notify } from '@/components/ui/app-toast';
import { cn } from '@/lib/utils';
import type { SessionWorkspaceFile } from '@/types';

type SessionWorkspaceFilesDrawerProps = {
  open: boolean;
  sessionId?: string;
  tenantId: string;
  onClose: () => void;
};

export default function SessionWorkspaceFilesDrawer({
  open,
  sessionId,
  tenantId,
  onClose,
}: SessionWorkspaceFilesDrawerProps) {
  const [files, setFiles] = useState<SessionWorkspaceFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState('');

  const loadFiles = useCallback(async () => {
    if (!open || !sessionId || !tenantId) {
      setFiles([]);
      setError('');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const query = new URLSearchParams({ tenant_id: tenantId });
      const rows = await api.get<SessionWorkspaceFile[]>(
        `/api/chat/sessions/${encodeURIComponent(sessionId)}/workspace-files?${query.toString()}`,
      );
      setFiles(rows);
    } catch (requestError) {
      setFiles([]);
      setError(requestError instanceof Error ? requestError.message : '文件列表加载失败');
    } finally {
      setLoading(false);
    }
  }, [open, sessionId, tenantId]);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  const uploads = useMemo(() => files.filter((file) => file.category === 'upload'), [files]);
  const generated = useMemo(() => files.filter((file) => file.category === 'generated'), [files]);

  async function downloadFile(file: SessionWorkspaceFile) {
    if (!sessionId || !tenantId) return;
    setDownloading(file.id);
    try {
      const query = new URLSearchParams({ tenant_id: tenantId });
      const blob = await api.blob(
        `/api/chat/sessions/${encodeURIComponent(sessionId)}/workspace-files/`
          + `${encodeURIComponent(file.id)}/download?${query.toString()}`,
      );
      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = file.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
      notify.success(`已下载文件：${file.filename}`);
    } catch (downloadError) {
      notify.error(downloadError instanceof Error ? downloadError.message : '文件下载失败');
    } finally {
      setDownloading('');
    }
  }

  return (
    <aside
      aria-label="本会话文件"
      className={cn(
        'z-20 h-full shrink-0 overflow-hidden bg-white transition-[width] duration-200 max-[700px]:fixed max-[700px]:inset-y-0 max-[700px]:right-0 max-[700px]:shadow-[-8px_0_24px_rgba(24,24,26,0.12)]',
        open ? 'w-[340px] border-l border-[#e3e7f1] max-[700px]:w-[min(340px,100vw)]' : 'w-0 border-l-0',
      )}
    >
      {open && (
        <div className="flex h-full w-[340px] flex-col max-[700px]:w-[min(340px,100vw)]">
          <div className="flex h-[56px] shrink-0 items-center justify-between border-b border-[#f0f1f4] px-[16px]">
            <div className="min-w-0">
              <h2 className="text-[14px] font-medium text-[#18181a]">本会话文件</h2>
              <p className="mt-[2px] truncate text-[11px] text-[#858b9c]">上传文件和最终生成文件</p>
            </div>
            <div className="flex items-center gap-[2px]">
              <button
                type="button"
                aria-label="刷新本会话文件"
                title="刷新"
                disabled={loading}
                onClick={() => void loadFiles()}
                className="inline-grid size-[30px] place-items-center rounded-[8px] text-[#757f9c] transition-colors hover:bg-[#f1f2f5] hover:text-[#18181a] disabled:cursor-wait disabled:opacity-50"
              >
                <StaffdeckIcon name="refresh" size={16} />
              </button>
              <button
                type="button"
                aria-label="关闭本会话文件"
                title="关闭"
                onClick={onClose}
                className="inline-grid size-[30px] place-items-center rounded-[8px] text-[#757f9c] transition-colors hover:bg-[#f1f2f5] hover:text-[#18181a]"
              >
                <StaffdeckIcon name="close" size={16} />
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-[14px]">
            {loading && files.length === 0 ? (
              <p className="px-[4px] py-[10px] text-[13px] text-[#858b9c]">正在加载文件…</p>
            ) : error ? (
              <div className="rounded-[10px] border border-[#f2cccc] bg-[#fff7f7] px-[10px] py-[9px] text-[12px] leading-[1.5] text-[#ba3e3e]">
                <p>{error}</p>
                <button
                  type="button"
                  onClick={() => void loadFiles()}
                  className="mt-[5px] font-medium underline underline-offset-2"
                >
                  重试
                </button>
              </div>
            ) : files.length === 0 ? (
              <div className="rounded-[12px] border border-dashed border-[#dce1eb] bg-[#fafbfc] px-[14px] py-[16px] text-[12px] leading-[1.65] text-[#757f9c]">
                该会话暂无可复用文件。上传文件或生成最终文件后，它们会显示在这里。
              </div>
            ) : (
              <div className="grid gap-[18px]">
                <FileGroup
                  title="上传文件"
                  files={uploads}
                  downloading={downloading}
                  onDownload={downloadFile}
                />
                <FileGroup
                  title="生成文件"
                  files={generated}
                  downloading={downloading}
                  onDownload={downloadFile}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}

type FileGroupProps = {
  title: string;
  files: SessionWorkspaceFile[];
  downloading: string;
  onDownload: (file: SessionWorkspaceFile) => Promise<void>;
};

function FileGroup({ title, files, downloading, onDownload }: FileGroupProps) {
  if (files.length === 0) return null;
  return (
    <section>
      <h3 className="mb-[7px] px-[3px] text-[12px] font-medium text-[#5b6273]">{title}</h3>
      <div className="grid gap-[6px]">
        {files.map((file) => {
          const isDownloading = downloading === file.id;
          return (
            <button
              type="button"
              key={file.id}
              disabled={isDownloading}
              aria-busy={isDownloading}
              aria-label={`下载文件 ${file.filename}`}
              onClick={() => void onDownload(file)}
              className="grid min-h-[50px] w-full grid-cols-[32px_minmax(0,1fr)_20px] items-center gap-[9px] rounded-[10px] border border-[#e3e7f1] bg-[#fafbfc] px-[8px] py-[7px] text-left transition-colors hover:border-[#c9d2e4] hover:bg-white disabled:cursor-wait disabled:opacity-60"
            >
              <span className="inline-grid size-[32px] place-items-center rounded-[8px] bg-[#eef0f4] text-[#464c5e]">
                <StaffdeckIcon name="file" size={17} />
              </span>
              <span className="grid min-w-0 gap-[2px]">
                <span className="truncate text-[12px] font-medium text-[#18181a]" data-i18n-ignore>{file.filename}</span>
                <span className="truncate text-[11px] text-[#858b9c]">
                  {isDownloading ? '下载中…' : fileMeta(file)}
                </span>
              </span>
              <StaffdeckIcon name="download" size={16} className="text-[#757f9c]" />
            </button>
          );
        })}
      </div>
    </section>
  );
}

function fileMeta(file: SessionWorkspaceFile): string {
  const date = new Date(file.created_at);
  const time = Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  const size = formatFileSize(file.size);
  return [size, time].filter(Boolean).join(' · ');
}

function formatFileSize(size: number): string {
  if (!Number.isFinite(size) || size < 0) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(size < 10 * 1024 ? 1 : 0)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
