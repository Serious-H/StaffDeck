import { cn } from '@/lib/utils';
import companyLogo from '../assets/company-logo.png';

export type BrandLogoProps = {
  /** Hide the "OpenBMB / StaffDeck" wordmark and only render the logo mark. */
  markOnly?: boolean;
  /** Size of the square logo mark in pixels. */
  markSize?: number;
  className?: string;
  /** Extra classes applied to the wordmark wrapper (e.g. to hide it responsively). */
  wordmarkClassName?: string;
};

/**
 * Company logo source is a horizontal raster image with white margins. Keep the
 * crop geometry here so the same supplied asset renders as a complete lockup
 * in expanded navigation and as its circular mark in collapsed navigation.
 */
const SOURCE_WIDTH = 1746;
const SOURCE_HEIGHT = 901;
const CONTENT_TOP = 282;
const CONTENT_HEIGHT = 330;
const CONTENT_LEFT = 145;
const CONTENT_WIDTH = 1460;
const MARK_LEFT = 145;
const MARK_WIDTH = 330;

function CompanyLogoImage({ markOnly, markSize }: Pick<BrandLogoProps, 'markOnly' | 'markSize'>) {
  const displayHeight = markOnly ? (markSize ?? 28) : 29;
  const displayWidth = markOnly
    ? displayHeight
    : Math.round((CONTENT_WIDTH / CONTENT_HEIGHT) * displayHeight);
  const cropLeft = markOnly ? MARK_LEFT : CONTENT_LEFT;
  const cropWidth = markOnly ? MARK_WIDTH : CONTENT_WIDTH;
  const scale = displayWidth / cropWidth;

  return (
    <span
      className="block shrink-0 overflow-hidden"
      style={{ width: displayWidth, height: displayHeight }}
    >
      <img
        src={companyLogo}
        alt="智园 AI Staff"
        className="block max-w-none"
        style={{
          width: SOURCE_WIDTH * scale,
          height: SOURCE_HEIGHT * scale,
          transform: `translate(-${cropLeft * scale}px, -${CONTENT_TOP * scale}px)`,
        }}
      />
    </span>
  );
}

/** Company logo lockup used across the enterprise console. */
export default function BrandLogo({
  markOnly = false,
  markSize = 28,
  className,
  wordmarkClassName,
}: BrandLogoProps) {
  return (
    <span className={cn('flex items-center gap-[8px] overflow-hidden p-[4px]', className)}>
      <CompanyLogoImage markOnly={markOnly} markSize={markSize} />
      {!markOnly && <span className={cn('hidden', wordmarkClassName)} aria-hidden="true" />}
    </span>
  );
}
