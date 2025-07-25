def generate_cucp_config(
    f1_ip,
    n2_ip,
    cucp_ip,
    amf_ip,
    near_ric_ip,
    template_path='./cucp.conf',
    output_path='./cucp_generated.conf'
):
    # Read the template config
    with open(template_path, 'r') as f:
        config = f.read()

    # Replace placeholders
    config = config.replace('@F1_IP_ADDRESS@', f1_ip)
    config = config.replace('@N2_IP_ADDRESS@', n2_ip)
    config = config.replace('@CUCP_IP_ADDRESS@', cucp_ip)
    config = config.replace('@AMF_IP_ADDRESS@', amf_ip)
    config = config.replace('@NEAR_RIC_IP_ADDRESS@', near_ric_ip)

    # Save the filled config
    with open(output_path, 'w') as f:
        f.write(config)

    print(f"Generated CUCP config at: {output_path}")


if __name__ == '__main__':
    # Define your IP addresses here
    F1_IP = '192.168.70.139'
    N2_IP = '192.168.70.139'
    CUCP_IP = '192.168.70.139'
    AMF_IP = '192.168.70.132'
    NEAR_RIC_IP = '192.168.70.154'

    generate_cucp_config(
        f1_ip=F1_IP,
        n2_ip=N2_IP,
        cucp_ip=CUCP_IP,
        amf_ip=AMF_IP,
        near_ric_ip=NEAR_RIC_IP
    )
