// SPDX-License-Identifier: GPL-3.0-or-later

#include "WriteApiKeysJob.h"

#include "GlobalStorage.h"
#include "JobQueue.h"

#include <QByteArray>
#include <QDir>
#include <QFile>
#include <QRandomGenerator>
#include <QStringList>

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <utility>

namespace
{
constexpr qsizetype MaxPasswdBytes = 16 * 1024 * 1024;

class ScopedFd
{
public:
    ScopedFd() = default;
    explicit ScopedFd( int fd )
        : m_fd( fd )
    {
    }

    ~ScopedFd()
    {
        if ( m_fd >= 0 )
        {
            ::close( m_fd );
        }
    }

    ScopedFd( const ScopedFd& ) = delete;
    ScopedFd& operator=( const ScopedFd& ) = delete;

    ScopedFd( ScopedFd&& other ) noexcept
        : m_fd( std::exchange( other.m_fd, -1 ) )
    {
    }

    ScopedFd& operator=( ScopedFd&& other ) noexcept
    {
        if ( this != &other )
        {
            if ( m_fd >= 0 )
            {
                ::close( m_fd );
            }
            m_fd = std::exchange( other.m_fd, -1 );
        }
        return *this;
    }

    explicit operator bool() const { return m_fd >= 0; }
    int get() const { return m_fd; }

private:
    int m_fd = -1;
};

void
wipeByteArray( QByteArray& bytes )
{
    std::fill( bytes.begin(), bytes.end(), '\0' );
    bytes.clear();
    bytes.squeeze();
}

void
wipeString( QString& text )
{
    text.detach();
    std::fill( text.begin(), text.end(), QChar( 0 ) );
    text.clear();
    text.squeeze();
}

bool
hasForbiddenControlCharacter( const QString& value )
{
    return value.contains( QChar( 0 ) ) || value.contains( QChar( '\r' ) ) || value.contains( QChar( '\n' ) );
}

void
appendShellQuoted( QByteArray& destination, const QString& value )
{
    QByteArray encoded = value.toUtf8();
    encoded.replace( "'", "'\"'\"'" );
    destination += '\'';
    destination += encoded;
    destination += '\'';
    wipeByteArray( encoded );
}

QString
systemError( const QString& action, int errorNumber )
{
    return QObject::tr( "%1: %2" ).arg( action, QString::fromLocal8Bit( std::strerror( errorNumber ) ) );
}

bool
isSafeComponent( const QString& component )
{
    return !component.isEmpty() && component != QStringLiteral( "." ) && component != QStringLiteral( ".." )
        && !component.contains( QChar( 0 ) ) && !component.contains( '/' );
}

ScopedFd
openDirectoryAt( int parentFd, const QString& component, QString& error )
{
    if ( !isSafeComponent( component ) )
    {
        error = QObject::tr( "A target directory component is unsafe." );
        return {};
    }

    const QByteArray encoded = QFile::encodeName( component );
    const int fd = ::openat( parentFd, encoded.constData(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC );
    if ( fd < 0 )
    {
        error = systemError( QObject::tr( "Could not open a target directory" ), errno );
        return {};
    }
    return ScopedFd( fd );
}

ScopedFd
openAbsoluteDirectoryWithoutSymlinks( const QString& path, QString& error )
{
    if ( path.isEmpty() || !QDir::isAbsolutePath( path ) || path == QStringLiteral( "/" )
         || QDir::cleanPath( path ) != path || path.contains( QChar( 0 ) ) )
    {
        error = QObject::tr( "The installation root path is unsafe." );
        return {};
    }

    ScopedFd current( ::open( "/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC ) );
    if ( !current )
    {
        error = systemError( QObject::tr( "Could not open the filesystem root" ), errno );
        return {};
    }

    const QStringList components = path.split( '/', Qt::SkipEmptyParts );
    for ( const QString& component : components )
    {
        ScopedFd next = openDirectoryAt( current.get(), component, error );
        if ( !next )
        {
            return {};
        }
        current = std::move( next );
    }
    return current;
}

struct TargetUser
{
    uid_t uid{};
    gid_t gid{};
    QString home;
};

bool
readAll( int fd, QByteArray& output, QString& error )
{
    std::array< char, 8192 > buffer{};
    while ( true )
    {
        const ssize_t count = ::read( fd, buffer.data(), buffer.size() );
        if ( count > 0 )
        {
            if ( output.size() > MaxPasswdBytes - count )
            {
                error = QObject::tr( "The target account database is unexpectedly large." );
                return false;
            }
            output.append( buffer.data(), count );
            continue;
        }
        if ( count == 0 )
        {
            return true;
        }
        if ( errno == EINTR )
        {
            continue;
        }
        error = systemError( QObject::tr( "Could not read the target account database" ), errno );
        return false;
    }
}

bool
readTargetUser( int targetRootFd, const QString& username, TargetUser& user, QString& error )
{
    ScopedFd etcDirectory = openDirectoryAt( targetRootFd, QStringLiteral( "etc" ), error );
    if ( !etcDirectory )
    {
        return false;
    }

    const int passwdFd = ::openat( etcDirectory.get(), "passwd", O_RDONLY | O_NOFOLLOW | O_CLOEXEC );
    if ( passwdFd < 0 )
    {
        error = systemError( QObject::tr( "Could not open the target account database" ), errno );
        return false;
    }
    ScopedFd passwdFile( passwdFd );

    struct stat passwdStatus
    {
    };
    if ( ::fstat( passwdFile.get(), &passwdStatus ) != 0 || !S_ISREG( passwdStatus.st_mode ) )
    {
        error = QObject::tr( "The target account database is not a regular file." );
        return false;
    }

    QByteArray passwdContents;
    if ( !readAll( passwdFile.get(), passwdContents, error ) )
    {
        wipeByteArray( passwdContents );
        return false;
    }

    bool found = false;
    for ( const QByteArray& line : passwdContents.split( '\n' ) )
    {
        const QList< QByteArray > fields = line.split( ':' );
        if ( fields.size() != 7 || fields.at( 0 ).contains( '\0' )
             || QString::fromUtf8( fields.at( 0 ) ) != username )
        {
            continue;
        }
        if ( found )
        {
            error = QObject::tr( "The installed user has duplicate account entries." );
            wipeByteArray( passwdContents );
            return false;
        }

        bool uidOk = false;
        bool gidOk = false;
        const qulonglong uidValue = fields.at( 2 ).toULongLong( &uidOk );
        const qulonglong gidValue = fields.at( 3 ).toULongLong( &gidOk );
        const QByteArray homeBytes = fields.at( 5 );
        const QString home = QString::fromUtf8( homeBytes );
        if ( !uidOk || !gidOk || uidValue == 0
             || uidValue > static_cast< qulonglong >( std::numeric_limits< uid_t >::max() )
             || gidValue > static_cast< qulonglong >( std::numeric_limits< gid_t >::max() )
             || homeBytes.contains( '\0' ) || home.toUtf8() != homeBytes || !home.startsWith( '/' )
             || home == QStringLiteral( "/" ) || QDir::cleanPath( home ) != home )
        {
            error = QObject::tr( "The installed user's account entry is unsafe." );
            wipeByteArray( passwdContents );
            return false;
        }

        user.uid = static_cast< uid_t >( uidValue );
        user.gid = static_cast< gid_t >( gidValue );
        user.home = home;
        found = true;
    }

    wipeByteArray( passwdContents );
    if ( !found )
    {
        error = QObject::tr( "The installed user was not found in the target account database." );
        return false;
    }
    return true;
}

ScopedFd
openTargetHome( int targetRootFd, const TargetUser& user, QString& error )
{
    const int duplicate = ::fcntl( targetRootFd, F_DUPFD_CLOEXEC, 0 );
    if ( duplicate < 0 )
    {
        error = systemError( QObject::tr( "Could not anchor the installed user's home" ), errno );
        return {};
    }
    ScopedFd current( duplicate );

    const QStringList components = user.home.split( '/', Qt::SkipEmptyParts );
    for ( const QString& component : components )
    {
        ScopedFd next = openDirectoryAt( current.get(), component, error );
        if ( !next )
        {
            return {};
        }
        current = std::move( next );
    }

    struct stat status
    {
    };
    if ( ::fstat( current.get(), &status ) != 0 || !S_ISDIR( status.st_mode ) || status.st_uid != user.uid
         || ( status.st_mode & 0022 ) != 0 )
    {
        error = QObject::tr( "The installed user's home directory is unsafe." );
        return {};
    }
    return current;
}

ScopedFd
ensureDirectoryAt( int parentFd,
                   const QString& name,
                   uid_t uid,
                   gid_t gid,
                   bool forcePrivateMode,
                   QString& error )
{
    if ( !isSafeComponent( name ) )
    {
        error = QObject::tr( "A private configuration path is unsafe." );
        return {};
    }

    const QByteArray encoded = QFile::encodeName( name );
    bool created = false;
    if ( ::mkdirat( parentFd, encoded.constData(), S_IRWXU ) == 0 )
    {
        created = true;
    }
    else if ( errno != EEXIST )
    {
        error = systemError( QObject::tr( "Could not create a private configuration directory" ), errno );
        return {};
    }

    ScopedFd directory = openDirectoryAt( parentFd, name, error );
    if ( !directory )
    {
        return {};
    }

    struct stat status
    {
    };
    if ( ::fstat( directory.get(), &status ) != 0 || !S_ISDIR( status.st_mode )
         || ( !created && status.st_uid != uid ) )
    {
        error = QObject::tr( "A private configuration directory has unsafe ownership." );
        return {};
    }

    if ( created || forcePrivateMode )
    {
        if ( ::fchown( directory.get(), uid, gid ) != 0 || ::fchmod( directory.get(), S_IRWXU ) != 0
             || ::fstat( directory.get(), &status ) != 0 || status.st_uid != uid || status.st_gid != gid
             || ( status.st_mode & 07777 ) != 0700 )
        {
            error = QObject::tr( "Could not protect a private configuration directory." );
            return {};
        }
    }
    else if ( ( status.st_mode & 0022 ) != 0 || ( status.st_mode & S_IRWXU ) != S_IRWXU )
    {
        error = QObject::tr( "The installed user's configuration directory is writable by another account." );
        return {};
    }

    if ( created && ::fsync( parentFd ) != 0 )
    {
        error = QObject::tr( "Could not make a private configuration directory durable." );
        return {};
    }

    return directory;
}

bool
writeAll( int fd, const QByteArray& contents, QString& error )
{
    qsizetype offset = 0;
    while ( offset < contents.size() )
    {
        const ssize_t written = ::write( fd, contents.constData() + offset, contents.size() - offset );
        if ( written > 0 )
        {
            offset += written;
            continue;
        }
        if ( written < 0 && errno == EINTR )
        {
            continue;
        }
        error = written == 0
            ? QObject::tr( "The private credential write made no progress." )
            : systemError( QObject::tr( "Could not write the private credential file" ), errno );
        return false;
    }
    return true;
}

bool
writeCredentialsAt( int directoryFd, QByteArray& contents, uid_t uid, gid_t gid, QString& error )
{
    struct stat existingStatus
    {
    };
    if ( ::fstatat( directoryFd, "env", &existingStatus, AT_SYMLINK_NOFOLLOW ) == 0 )
    {
        if ( !S_ISREG( existingStatus.st_mode ) || existingStatus.st_uid != uid )
        {
            error = QObject::tr( "The credential destination is not a user-owned regular file." );
            return false;
        }
    }
    else if ( errno != ENOENT )
    {
        error = systemError( QObject::tr( "Could not inspect the credential destination" ), errno );
        return false;
    }

    QByteArray temporaryName;
    ScopedFd temporaryFile;
    for ( int attempt = 0; attempt < 64 && !temporaryFile; ++attempt )
    {
        temporaryName = ".env.tmp." + QByteArray::number( static_cast< qulonglong >( ::getpid() ) ) + '.'
            + QByteArray::number( QRandomGenerator::system()->generate64(), 16 );
        const int fd = ::openat( directoryFd,
                                 temporaryName.constData(),
                                 O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC,
                                 S_IRUSR | S_IWUSR );
        if ( fd >= 0 )
        {
            temporaryFile = ScopedFd( fd );
        }
        else if ( errno != EEXIST )
        {
            error = systemError( QObject::tr( "Could not create the private credential file" ), errno );
            return false;
        }
    }
    if ( !temporaryFile )
    {
        error = QObject::tr( "Could not allocate a private credential file." );
        return false;
    }

    bool renamed = false;
    const auto cleanup = [&]() {
        ::unlinkat( directoryFd, renamed ? "env" : temporaryName.constData(), 0 );
    };

    struct stat temporaryStatus
    {
    };
    if ( ::fchown( temporaryFile.get(), uid, gid ) != 0
         || ::fchmod( temporaryFile.get(), S_IRUSR | S_IWUSR ) != 0
         || !writeAll( temporaryFile.get(), contents, error ) || ::fsync( temporaryFile.get() ) != 0
         || ::fstat( temporaryFile.get(), &temporaryStatus ) != 0 || temporaryStatus.st_uid != uid
         || temporaryStatus.st_gid != gid || ( temporaryStatus.st_mode & 07777 ) != 0600 )
    {
        if ( error.isEmpty() )
        {
            error = QObject::tr( "The private credential file could not be written safely." );
        }
        cleanup();
        return false;
    }

    if ( ::renameat( directoryFd, temporaryName.constData(), directoryFd, "env" ) != 0 )
    {
        error = systemError( QObject::tr( "Could not install the private credential file atomically" ), errno );
        cleanup();
        return false;
    }
    renamed = true;

    struct stat finalStatus
    {
    };
    if ( ::fstatat( directoryFd, "env", &finalStatus, AT_SYMLINK_NOFOLLOW ) != 0
         || !S_ISREG( finalStatus.st_mode ) || finalStatus.st_dev != temporaryStatus.st_dev
         || finalStatus.st_ino != temporaryStatus.st_ino || finalStatus.st_uid != uid || finalStatus.st_gid != gid
         || ( finalStatus.st_mode & 07777 ) != 0600 || ::fsync( directoryFd ) != 0 )
    {
        error = QObject::tr( "The credential file permissions, ownership, or durability check failed." );
        cleanup();
        return false;
    }

    return true;
}
}  // namespace

WriteApiKeysJob::WriteApiKeysJob( QString openRouterKey, QString groqKey )
    : Calamares::Job()
    , m_openRouterKey( std::move( openRouterKey ) )
    , m_groqKey( std::move( groqKey ) )
{
}

WriteApiKeysJob::~WriteApiKeysJob()
{
    clearSecrets();
}

QString
WriteApiKeysJob::prettyName() const
{
    return tr( "DarkOS AI credentials" );
}

QString
WriteApiKeysJob::prettyStatusMessage() const
{
    return tr( "Saving private AI service credentials…", "@status" );
}

Calamares::JobResult
WriteApiKeysJob::exec()
{
    QString error;
    QByteArray contents;

    if ( hasForbiddenControlCharacter( m_openRouterKey ) || hasForbiddenControlCharacter( m_groqKey ) )
    {
        clearSecrets();
        return Calamares::JobResult::error( tr( "Could not save AI service credentials." ),
                                            tr( "An API key contains an unsupported control character." ) );
    }
    if ( !m_openRouterKey.isEmpty() )
    {
        contents += "export DARKOS_OPENROUTER_API_KEY=";
        appendShellQuoted( contents, m_openRouterKey );
        contents += '\n';
    }
    if ( !m_groqKey.isEmpty() )
    {
        contents += "export DARKOS_GROQ_API_KEY=";
        appendShellQuoted( contents, m_groqKey );
        contents += '\n';
    }

    auto* queue = Calamares::JobQueue::instance();
    auto* storage = queue ? queue->globalStorage() : nullptr;
    const QString rootMountPoint = storage ? storage->value( "rootMountPoint" ).toString() : QString();
    const QString username = storage ? storage->value( "username" ).toString() : QString();
    if ( username.isEmpty() || username.contains( QChar( 0 ) ) || username.contains( ':' ) || username.contains( '/' ) )
    {
        wipeByteArray( contents );
        clearSecrets();
        return Calamares::JobResult::error( tr( "Could not save AI service credentials." ),
                                            tr( "The target user is unavailable or unsafe." ) );
    }

    ScopedFd targetRoot = openAbsoluteDirectoryWithoutSymlinks( rootMountPoint, error );
    TargetUser user;
    if ( !targetRoot || !readTargetUser( targetRoot.get(), username, user, error ) )
    {
        wipeByteArray( contents );
        clearSecrets();
        return Calamares::JobResult::error( tr( "Could not save AI service credentials." ), error );
    }

    ScopedFd targetHome = openTargetHome( targetRoot.get(), user, error );
    ScopedFd configDirectory;
    ScopedFd darkosDirectory;
    if ( targetHome )
    {
        configDirectory = ensureDirectoryAt(
            targetHome.get(), QStringLiteral( ".config" ), user.uid, user.gid, false, error );
    }
    if ( configDirectory )
    {
        darkosDirectory = ensureDirectoryAt(
            configDirectory.get(), QStringLiteral( "darkos" ), user.uid, user.gid, true, error );
    }
    if ( !targetHome || !configDirectory || !darkosDirectory
         || !writeCredentialsAt( darkosDirectory.get(), contents, user.uid, user.gid, error ) )
    {
        wipeByteArray( contents );
        clearSecrets();
        return Calamares::JobResult::error( tr( "Could not save AI service credentials." ), error );
    }

    wipeByteArray( contents );
    clearSecrets();
    return Calamares::JobResult::ok();
}

void
WriteApiKeysJob::clearSecrets() noexcept
{
    wipeString( m_openRouterKey );
    wipeString( m_groqKey );
}
